"""Решения судей: гонки, идемпотентность, откат.

Кружок зачитывается при приёме, судья приходит потом и либо подтверждает,
либо отменяет зачёт. Судей несколько, поэтому отметка «посмотрел» делается
одним UPDATE ... WHERE reviewed_at IS NULL: кто изменил строку — тот и решил,
остальные получают всплывашку и не трогают ни БД, ни беседу.

Отмена после закрытия дня даёт статус REVOKED: кружок уходит из месячного
счёта, но день остаётся закрытым и серия не рвётся задним числом.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.config import Settings
from bot.db.enums import AuditAction, SubmissionStatus
from bot.db.models import Submission, User
from bot.keyboards.judge import verdict_keyboard
from bot.repositories import audit as audit_repo
from bot.repositories import submissions as submissions_repo
from bot.services import announce as announce_service
from bot.services import stats as stats_service
from bot.services.challenge_day import current_day_number, day_end, local_day_for
from bot.utils import tg_retry
from bot.utils.timeutil import fmt_time, now_utc

logger = logging.getLogger(__name__)

VerdictStatus = Literal["ok", "already", "gone", "self", "error"]


@dataclass(frozen=True, slots=True)
class VerdictResult:
    status: VerdictStatus
    popup: str
    alert: bool = False


@dataclass(frozen=True, slots=True)
class UndoResult:
    ok: bool
    message: str


async def apply_verdict(
    session: AsyncSession,
    bot: Bot,
    settings: Settings,
    *,
    submission_id: int,
    judge: User,
    approve: bool,
    reason_text: str | None,
    card_text: str,
    edit_message: tuple[int, int] | None = None,
) -> VerdictResult:
    """edit_message — (chat_id, message_id) карточки, которую надо отредактировать."""
    # Значения судьи снимаем сразу: ниже мы делаем expire_all(), после которого
    # обращение к атрибутам отсоединённого объекта потянуло бы синхронный IO.
    judge_pk = judge.id
    judge_tg = judge.telegram_id
    judge_mention = judge.mention
    # Без @: судья и так виден по имени, а пинговать его на каждом
    # вердикте в общей беседе — верный способ его выжечь.
    judge_name = judge.display_name

    submission = await submissions_repo.get(session, submission_id)
    if submission is None:
        return VerdictResult("gone", texts.SUBMISSION_GONE, alert=True)

    if submission.participation.user.telegram_id == judge_tg and not settings.is_admin(
        judge_tg
    ):
        return VerdictResult("self", texts.SELF_JUDGE, alert=True)

    if submission.reviewed_at is not None:
        return _already(submission)

    now = now_utc()
    # Отмена уже после закрытия дня не рвёт серию задним числом: кружок
    # уходит из месячного счёта, но день остаётся закрытым.
    today = local_day_for(now, settings.tz, settings.day_boundary_hour)
    day_over = submission.day_date != today
    if approve:
        new_status = SubmissionStatus.APPROVED
    else:
        new_status = SubmissionStatus.REVOKED if day_over else SubmissionStatus.REJECTED

    claimed = await submissions_repo.claim_review(
        session,
        submission_id,
        status=new_status,
        judge_user_id=judge_pk,
        judge_telegram_id=judge_tg,
        at=now,
        reject_reason=reason_text,
    )
    # Коммитим сразу: пока транзакция открыта, второй судья ждёт блокировку.
    await session.commit()

    if not claimed:
        session.expire_all()
        fresh = await submissions_repo.get(session, submission_id)
        return _already(fresh) if fresh else VerdictResult("gone", texts.SUBMISSION_GONE, True)

    session.expire_all()
    submission = await submissions_repo.get(session, submission_id)
    assert submission is not None

    challenge = submission.participation.challenge
    current_day = current_day_number(
        now, challenge.start_date, settings.tz, settings.day_boundary_hour
    )
    streak, _best = await stats_service.refresh_streaks(
        session, submission.participation, current_day
    )

    await audit_repo.log(
        session,
        actor_id=judge_tg,
        action=AuditAction.APPROVE if approve else AuditAction.REJECT,
        target_type="submission",
        target_id=submission.id,
        payload={
            "day": submission.challenge_day,
            "reason": reason_text,
            "status": new_status.value,
        },
    )
    await session.commit()

    if edit_message is not None:
        await _render_resolved(
            bot, settings, edit_message, card_text, approve, judge_mention, now, reason_text
        )

    # Реакция меняется при любом решении: она и есть индикатор статуса на
    # самом кружке. 👀 означает «судья ещё не смотрел».
    await announce_service.set_reaction(
        bot,
        settings,
        submission,
        announce_service.REACTION_APPROVED if approve else announce_service.REACTION_REJECTED,
    )

    if approve:
        # Подтверждение — тихое: кружок уже помечен зачтённым, и реакции
        # достаточно. Сообщением бот отвечает только на отмену, где нужна причина.
        return VerdictResult("ok", "✅ Подтверждено")

    await announce_service.announce_verdict(
        bot,
        session,
        settings,
        submission,
        approve=approve,
        streak=streak,
        reason_text=reason_text,
        deadline=fmt_time(
            day_end(submission.day_date, settings.tz, settings.day_boundary_hour), settings.tz
        ),
        day_over=day_over,
        judge_name=judge_name,
    )
    await session.commit()

    return VerdictResult("ok", "❌ Зачёт отменён")


def _already(submission: Submission | None) -> VerdictResult:
    judge_name = "другим судьёй"
    if submission is not None and submission.judge is not None:
        judge_name = submission.judge.mention
    return VerdictResult("already", texts.ALREADY_JUDGED.format(judge=judge_name), alert=True)


async def _render_resolved(
    bot: Bot,
    settings: Settings,
    target: tuple[int, int],
    card_text: str,
    approve: bool,
    judge_mention: str,
    at,
    reason_text: str | None,
) -> None:
    chat_id, message_id = target
    stamp = fmt_time(at, settings.tz)
    if approve:
        new_text = texts.judge_card_resolved(card_text, True, judge_mention, stamp)
    else:
        new_text = texts.judge_card_rejected_with_reason(
            card_text, judge_mention, stamp, reason_text or "без причины"
        )
    await tg_retry.call_safe(
        bot.edit_message_text,
        chat_id=chat_id,
        message_id=message_id,
        text=new_text,
        reply_markup=None,
    )


async def undo(
    session: AsyncSession,
    bot: Bot,
    settings: Settings,
    *,
    submission_id: int,
    actor: User,
) -> UndoResult:
    actor_pk = actor.id
    actor_tg = actor.telegram_id

    submission = await submissions_repo.get(session, submission_id)
    if submission is None:
        return UndoResult(False, texts.SUBMISSION_GONE)
    if submission.reviewed_at is None:
        return UndoResult(False, texts.UNDO_NOT_JUDGED)

    is_admin = settings.is_admin(actor_tg)
    if not is_admin and submission.judge_id != actor_pk:
        return UndoResult(False, texts.UNDO_NOT_YOURS)

    # Окна на отмену нет: кружок зачитывается автоматически, и решение судьи —
    # это только отмена зачёта. Ошибиться в ней можно и заметить это через
    # неделю; держать человека без зачёта из-за таймера в 15 минут незачем.
    now = now_utc()

    # Сначала убираем реплай с вердиктом — его id хранится в строке,
    # которую сейчас обнулим.
    await announce_service.remove_verdict_message(bot, settings, submission)

    if not await submissions_repo.claim_undo(
        session, submission_id, undone_by=actor_tg, undone_at=now
    ):
        await session.rollback()
        return UndoResult(False, texts.UNDO_NOT_JUDGED)
    await session.commit()

    session.expire_all()
    submission = await submissions_repo.get(session, submission_id)
    assert submission is not None

    challenge = submission.participation.challenge
    current_day = current_day_number(
        now, challenge.start_date, settings.tz, settings.day_boundary_hour
    )
    await stats_service.refresh_streaks(session, submission.participation, current_day)
    await audit_repo.log(
        session,
        actor_id=actor_tg,
        action=AuditAction.UNDO,
        target_type="submission",
        target_id=submission.id,
        payload={"day": submission.challenge_day},
    )
    await session.commit()

    await _restore_judge_card(session, bot, settings, submission)
    await announce_service.reply_to_submission(
        bot,
        settings,
        submission,
        texts.verdict_undone(
            submission.participation.user.mention_html, submission.challenge_day
        ),
    )
    return UndoResult(True, texts.UNDO_OK.format(id=submission.id))


async def _restore_judge_card(
    session: AsyncSession, bot: Bot, settings: Settings, submission: Submission
) -> None:
    from bot.services import submissions as submissions_service

    if not submission.judge_message_id:
        return
    card_text = await submissions_service.build_card_text(
        session, settings, submission, submission.day_date
    )
    await tg_retry.call_safe(
        bot.edit_message_text,
        chat_id=settings.judges_chat_id,
        message_id=submission.judge_message_id,
        text=card_text,
        reply_markup=verdict_keyboard(submission.id),
    )
