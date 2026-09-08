"""Тренировки: сборка поста, публикация, RSVP, повтор из истории."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.config import Settings
from bot.db.enums import AuditAction, RsvpStatus, TrainingStatus
from bot.db.models import Training
from bot.keyboards.training import rsvp_keyboard
from bot.repositories import audit as audit_repo
from bot.repositories import checkins as checkins_repo
from bot.repositories import trainings as trainings_repo
from bot.services import weather as weather_service
from bot.utils import tg_retry
from bot.utils.timeutil import (
    fmt_time,
    format_day,
    format_day_with_weekday,
    now_utc,
    weekday_in,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PublishResult:
    ok: bool
    message: str


def render(training: Training, settings: Settings) -> str:
    return texts.training_post(
        weekday=weekday_in(training.start_at, settings.tz),
        day=format_day(training.start_at, settings.tz),
        clock=fmt_time(training.start_at, settings.tz),
        training_type=training.training_type,
        weather=training.weather,
        plan=training.plan,
        gear=training.gear,
        location=training.location,
        location_url=training.location_url,
        notes=training.notes,
        description=training.description,
        cancelled=training.status == TrainingStatus.CANCELLED,
    )


async def render_with_counts(
    session: AsyncSession, training: Training, settings: Settings
) -> tuple[str, dict[str, int]]:
    counts = await trainings_repo.counts(session, training.id)
    return render(training, settings), counts


async def publish(
    session: AsyncSession, bot: Bot, settings: Settings, training: Training, actor_id: int
) -> PublishResult:
    """Публикует или перезаписывает пост. Уже опубликованную тренировку
    не дублируем — редактируем существующее сообщение."""
    if not settings.trainings_enabled:
        return PublishResult(False, texts.TRAINING_NO_CHAT)

    text, counts = await render_with_counts(session, training, settings)
    # С опросом счётчик рисует сам Telegram — дублировать его кнопками незачем.
    markup = None if settings.use_poll else rsvp_keyboard(training.id, counts)

    if training.message_id:
        edited = await tg_retry.call_safe(
            bot.edit_message_text,
            chat_id=training.chat_id or settings.trainings_chat_id,
            message_id=training.message_id,
            text=text,
            reply_markup=markup,
        )
        if edited is not None:
            await audit_repo.log(
                session, actor_id=actor_id, action=AuditAction.TRAINING_UPDATED,
                target_type="training", target_id=training.id,
            )
            return PublishResult(True, texts.TRAINING_UPDATED)
        logger.warning("Не удалось отредактировать пост тренировки #%s", training.id)

    sent = await tg_retry.call_safe(
        bot.send_message,
        chat_id=settings.trainings_chat_id,
        text=text,
        reply_markup=markup,
        **settings.trainings_thread,
    )
    if sent is None:
        return PublishResult(False, texts.GENERIC_ERROR)

    await trainings_repo.set_message(
        session, training.id, settings.trainings_chat_id, sent.message_id
    )
    await send_poll(session, bot, settings, training)
    await audit_repo.log(
        session, actor_id=actor_id, action=AuditAction.TRAINING_PUBLISHED,
        target_type="training", target_id=training.id,
    )
    return PublishResult(True, texts.TRAINING_PUBLISHED)


async def send_poll(
    session: AsyncSession, bot: Bot, settings: Settings, training: Training
) -> None:
    """Неанонимный опрос: Telegram сам показывает, кто как ответил.

    Свою таблицу участников всё равно ведём — по ней шлются напоминания
    и считается статистика, а из опроса её не вытащишь.
    """
    if not settings.use_poll or training.poll_id:
        return

    poll = await tg_retry.call_safe(
        bot.send_poll,
        chat_id=settings.trainings_chat_id,
        question=texts.poll_question(
            format_day_with_weekday(training.start_at, settings.tz),
            fmt_time(training.start_at, settings.tz),
        ),
        options=texts.POLL_OPTIONS,
        is_anonymous=False,
        allows_multiple_answers=False,
        # Без reply_to_message_id: реплай в топике рисует цитату поста над
        # опросом и выглядит мусорно. Опрос идёт следом за постом сам по себе.
        **settings.trainings_thread,
    )
    if poll is None:
        logger.warning("Не удалось отправить опрос по тренировке #%s", training.id)
        return
    await trainings_repo.set_poll(session, training.id, poll.poll.id, poll.message_id)


async def apply_poll_answer(
    session: AsyncSession, training: Training, user_id: int, option_ids: list[int]
) -> None:
    """Голос в опросе = ответ на сбор. Пустой список — голос отозвали."""
    if not option_ids:
        await trainings_repo.clear_rsvp(session, training.id, user_id)
        return
    status = RsvpStatus(texts.POLL_ORDER[option_ids[0]])
    await trainings_repo.set_rsvp(session, training.id, user_id, status)


async def stop_poll(bot: Bot, settings: Settings, training: Training) -> None:
    """Тренировка отменена или удалена — закрываем опрос, чтобы в нём
    не продолжали голосовать."""
    if not training.poll_message_id:
        return
    await tg_retry.call_safe(
        bot.stop_poll,
        chat_id=training.chat_id or settings.trainings_chat_id,
        message_id=training.poll_message_id,
    )


async def republish(
    session: AsyncSession, bot: Bot, settings: Settings, training: Training, actor_id: int
) -> PublishResult:
    """Публикует пост заново — чтобы поднять его наверх ветки.

    Старый пост и опрос убираем: два сбора на одно занятие путают сильнее,
    чем помогают. Ответы участников живут в своей таблице и не теряются —
    напоминания придут тем же людям, но новый опрос Telegram нарисует пустым:
    перенести в него голоса через API нельзя.
    """
    if not training.message_id:
        return await publish(session, bot, settings, training, actor_id)

    chat_id = training.chat_id or settings.trainings_chat_id
    stale = 0
    for message_id in (training.message_id, training.poll_message_id):
        if message_id and not await tg_retry.call_safe(
            bot.delete_message, chat_id=chat_id, message_id=message_id
        ):
            stale += 1

    training.message_id = None
    training.poll_id = None
    training.poll_message_id = None
    await session.flush()

    result = await publish(session, bot, settings, training, actor_id)
    if result.ok and stale:
        # Старше 48 часов Telegram удалять не даёт — честно предупреждаем,
        # иначе админ не поймёт, откуда в ветке второй такой же пост.
        return PublishResult(True, texts.TRAINING_REPUBLISHED_STALE)
    if result.ok:
        return PublishResult(True, texts.TRAINING_REPUBLISHED)
    return result


async def purge(
    session: AsyncSession, bot: Bot, settings: Settings, training: Training
) -> int:
    """Сносит тренировку начисто: пост, опрос, присланные под ними скриншоты
    и саму запись.

    Отличается от отмены: там пост остаётся висеть с пометкой. Здесь чистим
    всё — это для тренировок, заведённых по ошибке или задублированных.
    Приходы уходят вместе с ней (в схеме ON DELETE CASCADE), поэтому вызывать
    стоит только после подтверждения.
    """
    chat_id = training.chat_id or settings.trainings_chat_id
    message_ids = [training.message_id, training.poll_message_id]
    for checkin in await checkins_repo.list_for_training(session, training.id):
        message_ids.append(checkin.message_id)
        message_ids.extend(checkin.bot_message_ids or [])

    removed = 0
    for message_id in message_ids:
        if not message_id:
            continue
        # call_safe, а не call: сообщение старше 48 часов Telegram удалять не
        # даёт, и на этом нельзя останавливать чистку остальных.
        if await tg_retry.call_safe(
            bot.delete_message, chat_id=chat_id, message_id=message_id
        ):
            removed += 1

    await trainings_repo.remove(session, training.id)
    await session.commit()
    logger.info("Тренировка #%s удалена, снято сообщений: %s", training.id, removed)
    return removed


async def refresh_post(
    session: AsyncSession, bot: Bot, settings: Settings, training: Training
) -> None:
    """Перерисовывает пост после изменения RSVP: счётчики живут на кнопках."""
    if not training.message_id:
        return
    text, counts = await render_with_counts(session, training, settings)
    await tg_retry.call_safe(
        bot.edit_message_text,
        chat_id=training.chat_id or settings.trainings_chat_id,
        message_id=training.message_id,
        text=text,
        reply_markup=None if settings.use_poll else rsvp_keyboard(training.id, counts),
    )


async def set_rsvp(
    session: AsyncSession,
    bot: Bot,
    settings: Settings,
    training: Training,
    user_id: int,
    status: RsvpStatus,
) -> str:
    await trainings_repo.set_rsvp(session, training.id, user_id, status)
    await session.commit()
    await refresh_post(session, bot, settings, training)
    return texts.RSVP_LABELS[status.value]


async def refresh_weather(
    session: AsyncSession, settings: Settings, training: Training
) -> str:
    """Прогноз за неделю до старта — гадание, поэтому погоду обновляем
    отдельно и ближе к делу. Сеть молчит — поле остаётся как было."""
    if not settings.weather_enabled:
        return training.weather
    text = await weather_service.describe(
        training.start_at, settings.tz, settings.weather_lat, settings.weather_lon
    )
    if text:
        training.weather = text
        await session.flush()
    return training.weather


async def copy_for_repeat(
    session: AsyncSession,
    source: Training,
    start_at: datetime,
    actor_id: int | None,
    club_id: int | None = None,
) -> Training:
    """Новая тренировка по образцу прошлой: меняются только дата и время.
    Ради этого отдельная таблица шаблонов не нужна — история и есть шаблон."""
    return await trainings_repo.create(
        session,
        club_id=club_id if club_id is not None else source.club_id,
        title=source.title,
        description=source.description,
        training_type=source.training_type,
        location=source.location,
        location_url=source.location_url,
        plan=source.plan,
        gear=source.gear,
        notes=source.notes,
        weather="",  # погода у каждой недели своя — её и правим
        poll_id=None,
        poll_message_id=None,
        latitude=source.latitude,
        longitude=source.longitude,
        start_at=start_at,
        created_by=actor_id,
        status=TrainingStatus.DRAFT,
        reminders_enabled=source.reminders_enabled,
        reminders_sent=[],
    )


async def participants_text(
    session: AsyncSession, training: Training, settings: Settings
) -> str:
    buckets: dict[str, list[str]] = {s.value: [] for s in RsvpStatus}
    for row in await trainings_repo.participants(session, training.id):
        buckets[row.status.value].append(row.user.mention)

    return texts.training_participants(
        day=format_day_with_weekday(training.start_at, settings.tz),
        clock=fmt_time(training.start_at, settings.tz),
        going=buckets[RsvpStatus.GOING.value],
        maybe=buckets[RsvpStatus.MAYBE.value],
        not_going=buckets[RsvpStatus.NOT_GOING.value],
    )


async def auto_draft(
    session: AsyncSession, settings: Settings, ahead_days: int = 2
) -> Training | None:
    """Готовит черновик на ближайший регулярный день по последней такой
    тренировке. Если на этот день уже что-то есть — ничего не делает."""
    if not settings.training_auto_draft or not settings.training_draft_weekdays:
        return None

    now = now_utc()
    today = now.astimezone(settings.tz).date()
    for shift in range(ahead_days + 1):
        day = today + timedelta(days=shift)
        if day.weekday() not in settings.training_draft_weekdays:
            continue

        day_start = datetime.combine(day, datetime.min.time(), tzinfo=settings.tz)
        if await trainings_repo.exists_on_day(
            session, day_start, day_start + timedelta(days=1), club_id=settings.active_club_id
        ):
            continue

        source = await trainings_repo.last_like(
            session, now, weekday=day.weekday(), club_id=settings.active_club_id
        )
        if source is None:
            continue

        start_at = datetime.combine(
            day, source.start_at.astimezone(settings.tz).time(), tzinfo=settings.tz
        )
        draft = await copy_for_repeat(
            session, source, start_at, source.created_by, settings.active_club_id
        )
        await refresh_weather(session, settings, draft)
        await session.commit()
        logger.info("Авто-черновик тренировки на %s создан по #%s", day, source.id)
        return draft

    return None
