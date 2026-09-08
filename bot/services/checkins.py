"""Приходы на тренировку: скриншот → зачёт → рейтинг.

Скриншот можно прислать двумя способами: реплаем на пост тренировки (тогда
привязка точная) или просто в топик приходов — там занятие подбирается по
времени, см. match_training.

Приход, как и кружок, засчитывается сразу. Судья не подтверждает, а только
отменяет — в любой момент. От случайных фото защищает не судья, а окно:
нет прошедшей тренировки — нечего и засчитывать.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.config import Settings
from bot.db.enums import AuditAction, CheckinStatus
from bot.db.models import Training, TrainingCheckin, User
from bot.keyboards.checkin import checkin_keyboard
from bot.repositories import audit as audit_repo
from bot.repositories import checkins as checkins_repo
from bot.repositories import trainings as trainings_repo
from bot.utils import tg_retry
from bot.utils.timeutil import fmt_time, format_day_with_weekday, now_utc

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AcceptResult:
    ok: bool
    text: str
    checkin_id: int | None = None


def _thread_of(checkin: TrainingCheckin, settings: Settings) -> dict[str, int]:
    """Ветка, в которой лежит отчёт. У старых приходов её нет — для них
    остаётся ветка тренировок, где они и были."""
    thread = checkin.thread_id or settings.checkins_thread_id or settings.trainings_thread_id
    return {"message_thread_id": thread} if thread else {}


async def match_training(
    session: AsyncSession, settings: Settings, user: User
) -> Training | None:
    """Подбирает тренировку для фото из топика приходов.

    Реплая там нет, поэтому привязываемся по времени: берём последнюю
    прошедшую тренировку внутри окна, по которой у человека ещё нет зачёта.
    Перебор от свежей к старой закрывает «сходил во вторник и в четверг,
    выкладываю оба отчёта» — второй скриншот уедет на предыдущее занятие.

    Окно — и есть защита от случайных фото: не было тренировки — не будет
    и зачёта.
    """
    now = now_utc()
    since = now - timedelta(hours=settings.checkin_window_hours)
    for training in await trainings_repo.recent_started(session, now, since, club_id=settings.active_club_id):
        existing = await checkins_repo.get_for(session, training.id, user.id)
        if existing is None or existing.status != CheckinStatus.APPROVED:
            return training
    return None


async def accept_photo(
    session: AsyncSession,
    bot: Bot,
    settings: Settings,
    *,
    training: Training,
    user: User,
    chat_id: int,
    message_id: int,
    file_id: str,
    file_unique_id: str,
    thread_id: int | None = None,
) -> AcceptResult:
    mention = user.mention_html
    # Ориентир — время самой тренировки, а не когда опубликовали пост и не
    # когда прислали скриншот: пост может висеть с прошлой недели.
    if training.start_at > now_utc():
        return AcceptResult(
            False,
            texts.checkin_too_early(
                mention,
                format_day_with_weekday(training.start_at, settings.tz),
                fmt_time(training.start_at, settings.tz),
            ),
        )

    existing = await checkins_repo.get_for(session, training.id, user.id)
    if existing and existing.status == CheckinStatus.APPROVED:
        return AcceptResult(False, texts.checkin_already_counted(mention))

    if existing:
        # Отменённый судьёй — переиспользуем строку: уникальный индекс
        # не даст завести вторую на ту же тренировку.
        checkin = await checkins_repo.replace_photo(
            session, existing, message_id=message_id, thread_id=thread_id,
            file_id=file_id, file_unique_id=file_unique_id,
        )
    else:
        checkin = await checkins_repo.create(
            session,
            training_id=training.id,
            user_id=user.id,
            chat_id=chat_id,
            thread_id=thread_id,
            message_id=message_id,
            file_id=file_id,
            file_unique_id=file_unique_id,
        )

    await audit_repo.log(
        session, actor_id=user.telegram_id, action=AuditAction.CHECKIN_SENT,
        target_type="checkin", target_id=checkin.id,
    )
    await session.commit()

    await send_to_judges(session, bot, settings, checkin, training, user)
    await session.commit()

    visits = await checkins_repo.count_for_user(session, user.id)
    return AcceptResult(
        True,
        texts.checkin_accepted(
            mention,
            format_day_with_weekday(training.start_at, settings.tz),
            fmt_time(training.start_at, settings.tz),
            visits,
        ),
        checkin_id=checkin.id,
    )


async def send_to_judges(
    session: AsyncSession,
    bot: Bot,
    settings: Settings,
    checkin: TrainingCheckin,
    training: Training,
    user: User,
) -> None:
    visits = await checkins_repo.count_for_user(session, user.id)
    card = texts.checkin_card(
        name=user.display_name,
        username=user.username,
        telegram_id=user.telegram_id,
        day=format_day_with_weekday(training.start_at, settings.tz),
        clock=fmt_time(training.start_at, settings.tz),
        location=training.location or "—",
        visits=visits,
    )
    try:
        photo = await tg_retry.call(
            bot.copy_message,
            chat_id=settings.judges_chat_id,
            from_chat_id=checkin.chat_id,
            message_id=checkin.message_id,
        )
        sent = await tg_retry.call(
            bot.send_message,
            chat_id=settings.judges_chat_id,
            text=card,
            reply_to_message_id=photo.message_id,
            reply_markup=checkin_keyboard(checkin.id),
        )
    except Exception:  # noqa: BLE001 — приход уже в БД, судьи увидят его в /checkins
        logger.exception("Не удалось отправить приход #%s судьям", checkin.id)
        return

    await checkins_repo.set_judge_message(session, checkin.id, sent.message_id)


@dataclass(frozen=True, slots=True)
class VerdictResult:
    status: str
    popup: str
    alert: bool = False


async def apply_verdict(
    session: AsyncSession,
    bot: Bot,
    settings: Settings,
    *,
    checkin_id: int,
    judge: User,
    approve: bool,
    reason: str | None = None,
) -> VerdictResult:
    judge_pk, judge_tg = judge.id, judge.telegram_id
    judge_name = judge.display_name

    checkin = await checkins_repo.get(session, checkin_id)
    if checkin is None:
        return VerdictResult("gone", texts.CHECKIN_GONE, alert=True)
    if checkin.user.telegram_id == judge_tg and not settings.is_admin(judge_tg):
        return VerdictResult("self", texts.SELF_JUDGE, alert=True)
    if approve and checkin.status == CheckinStatus.APPROVED:
        # Кнопка со старой карточки: подтверждать нечего, приход и так в зачёте.
        return VerdictResult("already", texts.CHECKIN_ALREADY_OK, alert=True)
    if checkin.status != CheckinStatus.APPROVED:
        who = checkin.judge.mention if checkin.judge else "другим судьёй"
        return VerdictResult("already", texts.ALREADY_JUDGED.format(judge=who), alert=True)

    now = now_utc()
    claimed = await checkins_repo.claim_verdict(
        session,
        checkin_id,
        status=CheckinStatus.APPROVED if approve else CheckinStatus.REJECTED,
        judge_user_id=judge_pk,
        judged_at=now,
        reject_reason=reason,
    )
    await session.commit()
    if not claimed:
        session.expire_all()
        fresh = await checkins_repo.get(session, checkin_id)
        who = fresh.judge.mention if fresh and fresh.judge else "другим судьёй"
        return VerdictResult("already", texts.ALREADY_JUDGED.format(judge=who), alert=True)

    session.expire_all()
    checkin = await checkins_repo.get(session, checkin_id)
    assert checkin is not None

    await audit_repo.log(
        session,
        actor_id=judge_tg,
        action=AuditAction.CHECKIN_APPROVED if approve else AuditAction.CHECKIN_REJECTED,
        target_type="checkin",
        target_id=checkin.id,
        payload={"reason": reason},
    )
    await session.commit()

    visits = await checkins_repo.count_for_user(session, checkin.user_id)
    text = (
        texts.checkin_approved(checkin.user.mention_html, visits, judge_name)
        if approve
        else texts.checkin_rejected(checkin.user.mention_html, reason or "без причины", judge_name)
    )
    sent = await tg_retry.call_safe(
        bot.send_message,
        chat_id=checkin.chat_id or settings.checkins_chat,
        text=text,
        reply_to_message_id=checkin.message_id,
        **_thread_of(checkin, settings),
    )
    await checkins_repo.remember_bot_message(
        session, checkin, sent.message_id if sent else None
    )
    await session.commit()
    return VerdictResult("ok", "✅ Приход засчитан" if approve else "❌ Отклонено")


async def cleanup(session: AsyncSession, bot: Bot, settings: Settings) -> int:
    """Убирает скриншоты и ответы бота из ветки через N часов после тренировки.

    Сам пост тренировки не трогаем: по нему видно историю и кто собирался.
    Приходы остаются в базе и в рейтинге — удаляются только сообщения.
    """
    if not settings.checkin_cleanup_hours:
        return 0

    cutoff = now_utc() - timedelta(hours=settings.checkin_cleanup_hours)
    removed = 0
    for checkin in await checkins_repo.due_cleanup(session, cutoff):
        chat_id = checkin.chat_id or settings.checkins_chat
        for message_id in [checkin.message_id, *(checkin.bot_message_ids or [])]:
            if message_id:
                await tg_retry.call_safe(
                    bot.delete_message, chat_id=chat_id, message_id=message_id
                )
        await checkins_repo.mark_cleaned(session, checkin, now_utc())
        removed += 1

    if removed:
        await session.commit()
        logger.info("Убрано скриншотов из ветки тренировок: %s", removed)
    return removed
