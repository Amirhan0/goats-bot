from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.config import Settings
from bot.db.enums import RejectReason
from bot.db.models import User
from bot.filters import IsJudge
from bot.keyboards.judge import VerdictCB, reject_reasons_keyboard, verdict_keyboard
from bot.repositories import submissions as submissions_repo
from bot.repositories import users as users_repo
from bot.services import challenge as challenge_service
from bot.services import moderation as moderation_service
from bot.services import submissions as submissions_service
from bot.services.challenge_day import local_day_for, month_start
from bot.utils.text_format import message_link
from bot.utils.timeutil import fmt_time, now_utc

logger = logging.getLogger(__name__)

router = Router(name="judges")


class JudgeStates(StatesGroup):
    custom_reason = State()


@router.callback_query(VerdictCB.filter(F.action == "approve"), IsJudge())
async def cb_approve(
    callback: CallbackQuery,
    callback_data: VerdictCB,
    bot: Bot,
    session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    await _verdict(callback, callback_data.submission_id, bot, session, user, settings, True, None)


@router.callback_query(VerdictCB.filter(F.action == "reject_menu"), IsJudge())
async def cb_reject_menu(
    callback: CallbackQuery,
    callback_data: VerdictCB,
    session: AsyncSession,
) -> None:
    submission = await submissions_repo.get(session, callback_data.submission_id)
    if submission is None:
        await callback.answer(texts.SUBMISSION_GONE, show_alert=True)
        return
    if submission.reviewed_at is not None:
        judge = submission.judge.mention if submission.judge else "другим судьёй"
        await callback.answer(texts.ALREADY_JUDGED.format(judge=judge), show_alert=True)
        return

    await callback.answer()
    await callback.message.edit_reply_markup(
        reply_markup=reject_reasons_keyboard(callback_data.submission_id)
    )


@router.callback_query(VerdictCB.filter(F.action == "back"), IsJudge())
async def cb_back(callback: CallbackQuery, callback_data: VerdictCB) -> None:
    await callback.answer()
    await callback.message.edit_reply_markup(
        reply_markup=verdict_keyboard(callback_data.submission_id)
    )


@router.callback_query(VerdictCB.filter(F.action == "reject"), IsJudge())
async def cb_reject(
    callback: CallbackQuery,
    callback_data: VerdictCB,
    bot: Bot,
    session: AsyncSession,
    user: User,
    settings: Settings,
    state: FSMContext,
) -> None:
    if callback_data.reason == RejectReason.CUSTOM.value:
        await state.set_state(JudgeStates.custom_reason)
        await state.update_data(
            submission_id=callback_data.submission_id,
            card_message_id=callback.message.message_id,
            card_text=callback.message.html_text,
        )
        await callback.answer()
        await callback.message.reply(texts.ASK_CUSTOM_REASON)
        return

    try:
        reason_text = texts.REJECT_REASON_TEXTS[RejectReason(callback_data.reason)]
    except ValueError:
        reason_text = callback_data.reason

    await _verdict(
        callback, callback_data.submission_id, bot, session, user, settings, False, reason_text
    )


@router.message(StateFilter(JudgeStates.custom_reason), IsJudge(), F.text)
async def on_custom_reason(
    message: Message,
    bot: Bot,
    session: AsyncSession,
    user: User,
    settings: Settings,
    state: FSMContext,
) -> None:
    if message.text and message.text.startswith("/cancel"):
        await state.clear()
        await message.reply(texts.CANCELLED)
        return

    data = await state.get_data()
    await state.clear()
    submission_id = data.get("submission_id")
    if submission_id is None:
        await message.reply(texts.GENERIC_ERROR)
        return

    result = await moderation_service.apply_verdict(
        session,
        bot,
        settings,
        submission_id=int(submission_id),
        judge=user,
        approve=False,
        reason_text=message.text.strip()[:200],
        card_text=data.get("card_text", ""),
        edit_message=(message.chat.id, int(data["card_message_id"]))
        if data.get("card_message_id")
        else None,
    )
    await message.reply(
        texts.CUSTOM_REASON_SAVED if result.status == "ok" else result.popup
    )


async def _verdict(
    callback: CallbackQuery,
    submission_id: int,
    bot: Bot,
    session: AsyncSession,
    user: User,
    settings: Settings,
    approve: bool,
    reason_text: str | None,
) -> None:
    logger.info(
        "Нажата кнопка судьи: submission=%s judge=%s approve=%s",
        submission_id,
        user.telegram_id,
        approve,
    )
    card_text = callback.message.html_text if callback.message else ""
    result = await moderation_service.apply_verdict(
        session,
        bot,
        settings,
        submission_id=submission_id,
        judge=user,
        approve=approve,
        reason_text=reason_text,
        card_text=card_text,
        edit_message=(callback.message.chat.id, callback.message.message_id)
        if callback.message
        else None,
    )
    logger.info("Результат: %s (%s)", result.status, result.popup)
    await callback.answer(result.popup, show_alert=result.alert)

    if result.status == "already" and callback.message is not None:
        # Кнопки у опоздавшего судьи уже неактуальны — убираем их.
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:  # noqa: BLE001
            logger.debug("Не удалось снять клавиатуру у устаревшей карточки")


# ── команды судьи ────────────────────────────────────────────────


@router.message(Command("queue"), IsJudge())
async def cmd_queue(
    message: Message, bot: Bot, session: AsyncSession, settings: Settings
) -> None:
    challenge = await challenge_service.get_current(session, settings)
    if challenge is None:
        await message.answer(texts.GENERIC_ERROR)
        return

    # Заодно чиним сдачи, чья карточка не доехала: /queue — то место,
    # куда судья приходит именно за «что ещё не проверено».
    await submissions_service.resend_missing_cards(session, bot, settings, challenge.id)

    day_date = local_day_for(now_utc(), settings.tz, settings.day_boundary_hour)
    pending = await submissions_repo.list_approved_on(session, challenge.id, day_date, limit=20)
    if not pending:
        await message.answer(texts.QUEUE_EMPTY)
        return

    # Считаем весь день, а не показанный кусок: иначе при 50 сдачах судья
    # увидит «20» и решит, что это всё.
    total = await submissions_repo.count_approved_on(session, challenge.id, day_date)
    lines = [texts.queue_header(total, shown=len(pending))]
    for submission in pending:
        user = submission.participation.user
        link = (
            message_link(settings.judges_chat_id, submission.judge_message_id)
            if submission.judge_message_id
            else None
        )
        head = (
            f"#{submission.id} · день {submission.challenge_day} · "
            f"{texts.esc(user.display_name)} · {fmt_time(submission.sent_at, settings.tz)}"
        )
        lines.append(f'<a href="{link}">{head}</a>' if link else head)

    await message.answer("\n".join(lines), disable_web_page_preview=True)


@router.message(Command("judges"))
async def cmd_judges(message: Message, session: AsyncSession, settings: Settings) -> None:
    """Открыта всем: имя судьи и так видно в вердикте, состав скрывать незачем.
    Источник истины — JUDGE_IDS из .env, а не членство в группе модерации."""
    judge_ids = settings.judge_ids
    if not judge_ids:
        await message.reply(texts.JUDGES_EMPTY)
        return

    known = await users_repo.map_by_telegram_ids(session, judge_ids)

    challenge = await challenge_service.get_current(session, settings)
    today = local_day_for(now_utc(), settings.tz, settings.day_boundary_hour)
    verdicts = (
        await submissions_repo.verdicts_by_judge(session, challenge.id, month_start(today))
        if challenge
        else {}
    )

    lines = []
    for telegram_id in judge_ids:
        user = known.get(telegram_id)
        lines.append(
            texts.judges_line(
                name=user.display_name if user else str(telegram_id),
                username=user.username if user else None,
                is_admin=settings.is_admin(telegram_id),
                known=user is not None,
                verdicts=verdicts.get(user.id, 0) if user else 0,
            )
        )

    await message.reply(
        texts.JUDGES_HEADER.format(count=len(judge_ids))
        + "\n".join(lines)
        + texts.JUDGES_FOOTER
    )


@router.message(Command("pending"), IsJudge())
async def cmd_pending(message: Message, session: AsyncSession, settings: Settings) -> None:
    challenge = await challenge_service.get_current(session, settings)
    day_date = local_day_for(now_utc(), settings.tz, settings.day_boundary_hour)
    count = (
        await submissions_repo.count_approved_on(session, challenge.id, day_date)
        if challenge
        else 0
    )
    await message.answer(texts.PENDING_COUNT.format(count=count))


@router.message(Command("undo"), IsJudge())
async def cmd_undo(
    message: Message,
    command: CommandObject,
    bot: Bot,
    session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    if not command.args or not command.args.strip().lstrip("#").isdigit():
        await message.answer(texts.UNDO_USAGE)
        return

    result = await moderation_service.undo(
        session,
        bot,
        settings,
        submission_id=int(command.args.strip().lstrip("#")),
        actor=user,
    )
    await message.answer(result.message)


@router.callback_query(VerdictCB.filter())
async def cb_not_a_judge(callback: CallbackQuery, user: User) -> None:
    """Кнопки видны всем участникам группы, но право судить даёт только
    JUDGE_IDS. Без этого обработчика у постороннего вечно крутился бы спиннер."""
    logger.info("Кнопку нажал не судья: %s", user.telegram_id)
    await callback.answer(texts.NOT_A_JUDGE, show_alert=True)
