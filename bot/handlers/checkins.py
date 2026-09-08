"""Скриншот Стравы в топик приходов (или реплаем на пост) + отмена зачёта."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.config import Settings
from bot.db.models import User
from bot.filters import IsJudge
from bot.keyboards.checkin import (
    REASON_TEXTS,
    CheckinCB,
    checkin_keyboard,
    checkin_reasons_keyboard,
)
from bot.repositories import checkins as checkins_repo
from bot.repositories import trainings as trainings_repo
from bot.services import checkins as checkins_service
from bot.utils.timeutil import month_name, month_start_at, now_utc

logger = logging.getLogger(__name__)

router = Router(name="checkins")


@router.message(F.photo)
async def on_screenshot(
    message: Message, bot: Bot, session: AsyncSession, user: User, settings: Settings
) -> None:
    """Скриншот Стравы = отметка о приходе. Два пути, как его принести.

    В топике приходов реплай не нужен: занятие подбирается по времени.
    В любом другом месте по-прежнему нужен ответ на пост тренировки — иначе
    бот трогал бы каждое фото в чате.
    """
    in_checkins_topic = settings.in_checkins_thread(
        message.chat.id, message.message_thread_id
    )

    if in_checkins_topic:
        training = await checkins_service.match_training(session, settings, user)
        if training is None:
            # Тренировки в окне нет — значит, это просто фото, а не отчёт.
            await message.reply(texts.checkin_no_training(user.mention_html))
            return
    else:
        if message.chat.id != settings.trainings_chat_id or message.reply_to_message is None:
            return
        training = await trainings_repo.get_by_message(
            session, message.reply_to_message.message_id
        )
        if training is None:
            return  # ответили не на тренировку — это просто фото в чате

    photo = message.photo[-1]
    result = await checkins_service.accept_photo(
        session,
        bot,
        settings,
        training=training,
        user=user,
        chat_id=message.chat.id,
        thread_id=message.message_thread_id,
        message_id=message.message_id,
        file_id=photo.file_id,
        file_unique_id=photo.file_unique_id,
    )
    sent = await message.reply(result.text)
    if result.checkin_id:
        checkin = await checkins_repo.get(session, result.checkin_id)
        if checkin:
            await checkins_repo.remember_bot_message(session, checkin, sent.message_id)
            await session.commit()


# ── судейство ────────────────────────────────────────────────────


@router.callback_query(CheckinCB.filter(F.action == "approve"), IsJudge())
async def cb_approve(
    callback: CallbackQuery,
    callback_data: CheckinCB,
    bot: Bot,
    session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    await _verdict(callback, callback_data.checkin_id, bot, session, user, settings, True, None)


@router.callback_query(CheckinCB.filter(F.action == "reject_menu"), IsJudge())
async def cb_reject_menu(callback: CallbackQuery, callback_data: CheckinCB) -> None:
    await callback.answer()
    await callback.message.edit_reply_markup(
        reply_markup=checkin_reasons_keyboard(callback_data.checkin_id)
    )


@router.callback_query(CheckinCB.filter(F.action == "back"), IsJudge())
async def cb_back(callback: CallbackQuery, callback_data: CheckinCB) -> None:
    await callback.answer()
    await callback.message.edit_reply_markup(
        reply_markup=checkin_keyboard(callback_data.checkin_id)
    )


@router.callback_query(CheckinCB.filter(F.action == "reject"), IsJudge())
async def cb_reject(
    callback: CallbackQuery,
    callback_data: CheckinCB,
    bot: Bot,
    session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    reason = REASON_TEXTS.get(callback_data.reason or "", callback_data.reason)
    await _verdict(callback, callback_data.checkin_id, bot, session, user, settings, False, reason)


async def _verdict(
    callback: CallbackQuery,
    checkin_id: int,
    bot: Bot,
    session: AsyncSession,
    user: User,
    settings: Settings,
    approve: bool,
    reason: str | None,
) -> None:
    logger.info("Вердикт по приходу %s: judge=%s approve=%s", checkin_id, user.telegram_id, approve)
    result = await checkins_service.apply_verdict(
        session, bot, settings, checkin_id=checkin_id, judge=user, approve=approve, reason=reason
    )
    await callback.answer(result.popup, show_alert=result.alert)
    if result.status in {"ok", "already"} and callback.message is not None:
        await callback.message.edit_reply_markup(reply_markup=None)


@router.callback_query(CheckinCB.filter())
async def cb_not_a_judge(callback: CallbackQuery) -> None:
    await callback.answer(texts.NOT_A_JUDGE, show_alert=True)


# ── рейтинг и очередь ────────────────────────────────────────────


async def _send_top(
    message: Message, session: AsyncSession, user: User, since: datetime | None
) -> None:
    rows = await checkins_repo.leaderboard(session, since=since, limit=10)
    if not rows:
        await message.reply(texts.ATTENDANCE_EMPTY)
        return
    lines = [
        texts.attendance_line(i, row.name, row.visits, is_me=row.telegram_id == user.telegram_id)
        for i, row in enumerate(rows, start=1)
    ]
    month = month_name(since.month) if since else None
    await message.reply(texts.attendance_top(month, lines))


@router.message(Command("attendance"))
async def cmd_attendance(
    message: Message, session: AsyncSession, user: User, settings: Settings
) -> None:
    await _send_top(message, session, user, month_start_at(settings.tz))


@router.message(Command("attendance_all"))
async def cmd_attendance_all(message: Message, session: AsyncSession, user: User) -> None:
    await _send_top(message, session, user, None)


@router.message(Command("checkins"), IsJudge())
async def cmd_checkins(message: Message, session: AsyncSession, settings: Settings) -> None:
    since = now_utc() - timedelta(hours=24)
    items = await checkins_repo.recent(session, since)
    if not items:
        await message.reply(texts.CHECKINS_QUEUE_EMPTY)
        return
    await message.reply(texts.CHECKINS_PENDING.format(count=len(items)))
