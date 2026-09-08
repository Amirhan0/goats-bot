"""Приём кружка от участника: проверки → запись → карточка судьям."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.config import Settings
from bot.db.enums import AuditAction, ParticipationStatus
from bot.db.models import Submission, User
from bot.keyboards.judge import verdict_keyboard
from bot.repositories import audit as audit_repo
from bot.repositories import participations as participations_repo
from bot.repositories import submissions as submissions_repo
from bot.services import challenge as challenge_service
from bot.services import daily_code as daily_code_service
from bot.services import motivation
from bot.services import stats as stats_service
from bot.services.anti_cheat import (
    RejectCode,
    SubmissionContext,
    VideoNoteMeta,
    check_submission,
)
from bot.services.challenge_day import (
    day_number,
    is_challenge_running,
    local_day_for,
    month_start,
    seconds_to_day_end,
)
from bot.utils import tg_retry
from bot.utils.timeutil import month_name

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AcceptOutcome:
    accepted: bool
    text: str
    submission_id: int | None = None


async def accept_video_note(
    session: AsyncSession,
    bot: Bot,
    settings: Settings,
    *,
    user: User,
    chat_id: int,
    message_id: int,
    file_id: str,
    meta: VideoNoteMeta,
) -> AcceptOutcome:
    challenge = await challenge_service.get_current(session, settings)
    if challenge is None:
        return AcceptOutcome(False, texts.rejection(RejectCode.CHALLENGE_INACTIVE))
    mention = user.mention_html

    day_date = local_day_for(meta.sent_at, settings.tz, settings.day_boundary_hour)
    current_day = day_number(day_date, challenge.start_date)

    participation = await participations_repo.get(session, user.id, challenge.id)
    previous = (
        await submissions_repo.last_attempt(session, participation.id, current_day)
        if participation
        else None
    )
    since_prev = (
        int((meta.sent_at - previous.sent_at).total_seconds()) if previous is not None else None
    )
    attempt_no = (
        await submissions_repo.next_attempt_no(session, participation.id, current_day)
        if participation
        else 1
    )

    ctx = SubmissionContext(
        is_registered=participation is not None,
        participation_active=(
            participation is not None and participation.status == ParticipationStatus.ACTIVE
        ),
        user_blocked=user.is_blocked,
        challenge_active=challenge.is_active,
        challenge_started=current_day >= 1,
        challenge_finished=not is_challenge_running(
            meta.sent_at,
            challenge.start_date,
            challenge.end_date,
            settings.tz,
            settings.day_boundary_hour,
        )
        and current_day >= 1,
        min_duration=challenge.min_duration_sec,
        max_duration=challenge.max_duration_sec,
        duplicate_exists=await submissions_repo.file_unique_exists(
            session, meta.file_unique_id
        ),
        current_day=current_day,
        seconds_to_deadline=seconds_to_day_end(
            meta.sent_at, settings.tz, settings.day_boundary_hour
        ),
        attempt_no=attempt_no,
        seconds_since_prev_attempt=since_prev,
        last_minutes_flag=settings.last_minutes_flag,
    )

    result = check_submission(meta, ctx)
    if not result.ok:
        assert result.reject is not None
        return AcceptOutcome(
            False,
            texts.rejection(
                result.reject,
                mention=mention,
                duration=meta.duration,
                start_date=challenge.start_date.strftime("%d.%m.%Y"),
            ),
        )

    assert participation is not None
    created = await submissions_repo.create(
        session,
        participation_id=participation.id,
        challenge_day=current_day,
        day_date=day_date,
        chat_id=chat_id,
        message_id=message_id,
        file_id=file_id,
        file_unique_id=meta.file_unique_id,
        duration=meta.duration,
        sent_at=meta.sent_at,
        attempt_no=attempt_no,
        flags=result.flag_values,
    )
    # Перечитываем с joinedload: у свежесозданного объекта связи не загружены,
    # а ленивая подгрузка в asyncio недопустима.
    submission = await submissions_repo.get(session, created.id)
    assert submission is not None
    await audit_repo.log(
        session,
        actor_id=user.telegram_id,
        action=AuditAction.SUBMIT,
        target_type="submission",
        target_id=submission.id,
        payload={"day": current_day, "attempt": attempt_no, "flags": result.flag_values},
    )

    # Коммит до похода в Telegram. Иначе запись держит единственный на всю базу
    # writer-лок всё время отправки карточек (а это N судей и до трёх ретраев
    # на каждого), и параллельные кружки валятся с «database is locked».
    await session.commit()

    await send_to_judges(session, bot, settings, submission, day_date=day_date)

    # Счёт и серия — уже с учётом этого кружка: он зачтён при создании.
    since = month_start(day_date)
    circles_month = await submissions_repo.count_approved(session, participation.id, since)
    circles_total = await submissions_repo.count_approved(session, participation.id)
    streak, _best = await stats_service.refresh_streaks(session, participation, current_day)
    # Тем же порядком: дальше хендлер ставит реакцию и пишет похвалу в чат,
    # и лок на это время держать незачем.
    await session.commit()

    return AcceptOutcome(
        True,
        texts.accepted(
            mention,
            current_day,
            attempt_no,
            praise=motivation.pick_praise(),
            circles_month=circles_month,
            month=month_name(day_date.month),
            streak=streak,
            quote=motivation.pick_quote(settings.quotes_path),
            milestone=motivation.milestone(circles_total),
        ),
        submission_id=submission.id,
    )


async def resend_missing_cards(
    session: AsyncSession, bot: Bot, settings: Settings, challenge_id: int
) -> int:
    """Досылает карточки судьям для сдач, у которых их нет. Без карточки
    нет кнопок, а значит вердикт невозможен и участник заперт до конца дня."""
    orphans = await submissions_repo.list_pending_without_card(session, challenge_id)
    for submission in orphans:
        await send_to_judges(
            session, bot, settings, submission, day_date=submission.day_date
        )
    if orphans:
        await session.commit()
        logger.info("Дослано карточек судьям: %s", len(orphans))
    return len(orphans)


async def build_card_text(
    session: AsyncSession, settings: Settings, submission: Submission, day_date: date
) -> str:
    participation = submission.participation
    challenge = participation.challenge
    progress = await stats_service.get_progress(session, participation, submission.challenge_day)
    code = await daily_code_service.ensure_code(session, challenge, day_date, settings)
    user = participation.user

    return texts.judge_card(
        submission_id=submission.id,
        telegram_id=user.telegram_id,
        task=settings.challenge_task,
        day=submission.challenge_day,
        name=user.display_name,
        username=user.username,
        duration=submission.duration,
        attempt=submission.attempt_no,
        code_word=code,
        streak=progress.current_streak,
        approved=progress.approved,
        total=progress.total,
        percent=progress.percent,
        flags=list(submission.anti_cheat_flags or []),
    )


async def send_to_judges(
    session: AsyncSession,
    bot: Bot,
    settings: Settings,
    submission: Submission,
    *,
    day_date: date,
) -> None:
    """Карточка = копия кружка + текстовое сообщение с кнопками реплаем на неё.
    Редактируется и хранится в БД именно текстовое (judge_message_id)."""
    card_text = await build_card_text(session, settings, submission, day_date)

    try:
        video = await tg_retry.call(
            bot.copy_message,
            chat_id=settings.judges_chat_id,
            from_chat_id=submission.chat_id or settings.participants_chat_id,
            message_id=submission.message_id,
        )
        card = await tg_retry.call(
            bot.send_message,
            chat_id=settings.judges_chat_id,
            text=card_text,
            reply_to_message_id=video.message_id,
            reply_markup=verdict_keyboard(submission.id),
        )
    except Exception:  # noqa: BLE001
        # Сдача уже в БД и видна в /queue — судьи не потеряют её.
        logger.exception("Не удалось отправить карточку судьям для сдачи #%s", submission.id)
        return

    await submissions_repo.set_judge_messages(
        session, submission.id, card.message_id, video.message_id
    )
