from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from bot.db.enums import RsvpStatus, TrainingStatus
from bot.db.models import Training, TrainingParticipant, User


def _for_club(stmt, club_id: int | None):
    """Тренировки чужой группы в выборку попадать не должны.

    club_id=None — установка без клубов (или старые записи, оставшиеся
    без привязки): тогда фильтра нет и поведение прежнее.
    """
    return stmt.where(Training.club_id == club_id) if club_id is not None else stmt


async def get(session: AsyncSession, training_id: int) -> Training | None:
    return await session.scalar(
        select(Training).where(Training.id == training_id).options(joinedload(Training.author))
    )


async def get_by_message(session: AsyncSession, message_id: int) -> Training | None:
    """Ответить можно и на пост, и на опрос под ним.

    Опрос висит следом за постом и часто оказывается последним сообщением
    в ветке — реплаем в него попадают чаще, чем в сам пост. Раньше такой
    скриншот молча пропадал: тренировка по нему не находилась.
    """
    return await session.scalar(
        select(Training).where(
            or_(Training.message_id == message_id, Training.poll_message_id == message_id)
        )
    )


async def get_by_poll(session: AsyncSession, poll_id: str) -> Training | None:
    return await session.scalar(select(Training).where(Training.poll_id == poll_id))


async def set_poll(
    session: AsyncSession, training_id: int, poll_id: str, message_id: int
) -> None:
    await session.execute(
        update(Training)
        .where(Training.id == training_id)
        .values(poll_id=poll_id, poll_message_id=message_id)
    )


async def clear_rsvp(session: AsyncSession, training_id: int, user_id: int) -> None:
    """Отозвал голос в опросе — убираем и у себя, иначе напоминание уйдёт
    тому, кто уже передумал."""
    await session.execute(
        delete(TrainingParticipant).where(
            TrainingParticipant.training_id == training_id,
            TrainingParticipant.user_id == user_id,
        )
    )


async def create(session: AsyncSession, **fields: Any) -> Training:
    training = Training(**fields)
    session.add(training)
    await session.flush()
    return training


async def upcoming(
    session: AsyncSession,
    now: datetime,
    *,
    limit: int = 20,
    until: datetime | None = None,
    only_published: bool = False,
    club_id: int | None = None,
) -> list[Training]:
    stmt = _for_club(
        select(Training).where(
            Training.start_at >= now, Training.status != TrainingStatus.CANCELLED
        ),
        club_id,
    )
    if until is not None:
        stmt = stmt.where(Training.start_at <= until)
    if only_published:
        stmt = stmt.where(Training.status == TrainingStatus.PUBLISHED)
    return list(await session.scalars(stmt.order_by(Training.start_at).limit(limit)))


async def past(
    session: AsyncSession, now: datetime, limit: int = 10, club_id: int | None = None
) -> list[Training]:
    stmt = _for_club(
        select(Training).where(
            Training.start_at < now, Training.status != TrainingStatus.CANCELLED
        ),
        club_id,
    )
    return list(
        await session.scalars(stmt.order_by(Training.start_at.desc()).limit(limit))
    )


async def recent_started(
    session: AsyncSession, now: datetime, since: datetime, club_id: int | None = None
) -> list[Training]:
    """Прошедшие тренировки внутри окна отчётов, свежая — первой.

    По ним разбирается фото из топика приходов: реплая там нет, и привязку
    приходится выбирать по времени. Отменённые не берём — на них не ходили.
    """
    stmt = _for_club(
        select(Training).where(
            Training.start_at <= now,
            Training.start_at >= since,
            Training.status != TrainingStatus.CANCELLED,
        ),
        club_id,
    )
    return list(await session.scalars(stmt.order_by(Training.start_at.desc())))


async def drafts(
    session: AsyncSession, limit: int = 20, club_id: int | None = None
) -> list[Training]:
    stmt = _for_club(select(Training).where(Training.status == TrainingStatus.DRAFT), club_id)
    return list(await session.scalars(stmt.order_by(Training.start_at).limit(limit)))


async def last_like(
    session: AsyncSession,
    now: datetime,
    weekday: int | None = None,
    club_id: int | None = None,
) -> Training | None:
    """Последняя прошедшая тренировка — основа для «повторить».

    weekday ограничивает поиск нужным днём недели: у вторника и четверга
    обычно разные тренировки, и подставлять чужую не надо. SQLite умеет
    strftime('%w'), где воскресенье = 0, поэтому переводим номер дня.
    """
    stmt = _for_club(
        select(Training).where(
            Training.start_at < now, Training.status == TrainingStatus.PUBLISHED
        ),
        club_id,
    )
    if weekday is not None:
        sqlite_dow = str((weekday + 1) % 7)
        stmt = stmt.where(func.strftime("%w", Training.start_at) == sqlite_dow)
    return await session.scalar(stmt.order_by(Training.start_at.desc()).limit(1))


async def exists_on_day(
    session: AsyncSession, day_start: datetime, day_end: datetime, club_id: int | None = None
) -> bool:
    """Есть ли уже тренировка в этот день — чтобы авто-черновик не плодил дубли."""
    stmt = _for_club(
        select(func.count(Training.id)).where(
            Training.start_at >= day_start,
            Training.start_at < day_end,
            Training.status != TrainingStatus.CANCELLED,
        ),
        club_id,
    )
    return bool(await session.scalar(stmt))


async def due_reminders(
    session: AsyncSession, now: datetime, horizon: datetime, club_id: int | None = None
) -> list[Training]:
    """Опубликованные тренировки, старт которых уже близко."""
    stmt = _for_club(
        select(Training).where(
            Training.status == TrainingStatus.PUBLISHED,
            Training.reminders_enabled.is_(True),
            Training.start_at > now,
            Training.start_at <= horizon,
        ),
        club_id,
    )
    return list(await session.scalars(stmt.order_by(Training.start_at)))


async def set_message(
    session: AsyncSession, training_id: int, chat_id: int, message_id: int
) -> None:
    await session.execute(
        update(Training)
        .where(Training.id == training_id)
        .values(chat_id=chat_id, message_id=message_id, status=TrainingStatus.PUBLISHED)
    )


async def mark_reminder_sent(session: AsyncSession, training: Training, hours: int) -> None:
    training.reminders_sent = [*(training.reminders_sent or []), hours]
    await session.flush()


async def remove(session: AsyncSession, training_id: int) -> None:
    await session.execute(delete(Training).where(Training.id == training_id))


# ── участники ────────────────────────────────────────────────────


async def set_rsvp(
    session: AsyncSession, training_id: int, user_id: int, status: RsvpStatus
) -> None:
    """Один человек — один актуальный ответ: обновляем, а не добавляем."""
    existing = await session.scalar(
        select(TrainingParticipant).where(
            TrainingParticipant.training_id == training_id,
            TrainingParticipant.user_id == user_id,
        )
    )
    if existing is None:
        session.add(
            TrainingParticipant(training_id=training_id, user_id=user_id, status=status)
        )
    else:
        existing.status = status
    await session.flush()


async def counts(session: AsyncSession, training_id: int) -> dict[str, int]:
    rows = await session.execute(
        select(TrainingParticipant.status, func.count())
        .where(TrainingParticipant.training_id == training_id)
        .group_by(TrainingParticipant.status)
    )
    result = {s.value: 0 for s in RsvpStatus}
    for status, total in rows:
        result[getattr(status, "value", status)] = total
    return result


async def participants(
    session: AsyncSession, training_id: int, status: RsvpStatus | None = None
) -> list[TrainingParticipant]:
    stmt = select(TrainingParticipant).where(TrainingParticipant.training_id == training_id)
    if status is not None:
        stmt = stmt.where(TrainingParticipant.status == status)
    return list(
        await session.scalars(
            stmt.options(joinedload(TrainingParticipant.user)).order_by(
                TrainingParticipant.updated_at
            )
        )
    )


async def going_telegram_ids(session: AsyncSession, training_id: int) -> list[int]:
    rows = await session.scalars(
        select(User.telegram_id)
        .join(TrainingParticipant, TrainingParticipant.user_id == User.id)
        .where(
            TrainingParticipant.training_id == training_id,
            TrainingParticipant.status == RsvpStatus.GOING,
        )
    )
    return list(rows)


async def user_history(session: AsyncSession, user_id: int) -> dict[str, int]:
    rows = await session.execute(
        select(TrainingParticipant.status, func.count())
        .where(TrainingParticipant.user_id == user_id)
        .group_by(TrainingParticipant.status)
    )
    return {getattr(s, "value", s): n for s, n in rows}
