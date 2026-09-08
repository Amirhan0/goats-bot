from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from bot.db.enums import ParticipationStatus
from bot.db.models import Participation, User


async def get(session: AsyncSession, user_id: int, challenge_id: int) -> Participation | None:
    return await session.scalar(
        select(Participation)
        .where(Participation.user_id == user_id, Participation.challenge_id == challenge_id)
        .options(joinedload(Participation.user))
    )


async def get_by_telegram_id(
    session: AsyncSession, telegram_id: int, challenge_id: int
) -> Participation | None:
    return await session.scalar(
        select(Participation)
        .join(User)
        .where(User.telegram_id == telegram_id, Participation.challenge_id == challenge_id)
        .options(joinedload(Participation.user))
    )


async def get_by_id(session: AsyncSession, participation_id: int) -> Participation | None:
    return await session.scalar(
        select(Participation)
        .where(Participation.id == participation_id)
        .options(joinedload(Participation.user))
    )


async def create(
    session: AsyncSession, *, user_id: int, challenge_id: int, join_day: int
) -> Participation:
    participation = Participation(
        user_id=user_id,
        challenge_id=challenge_id,
        join_day=max(1, join_day),
        status=ParticipationStatus.ACTIVE,
    )
    session.add(participation)
    await session.flush()
    return participation


async def reactivate(session: AsyncSession, participation: Participation) -> Participation:
    participation.status = ParticipationStatus.ACTIVE
    participation.left_at = None
    await session.flush()
    return participation


async def leave(
    session: AsyncSession, participation: Participation, at: datetime
) -> Participation:
    participation.status = ParticipationStatus.DROPPED
    participation.left_at = at
    participation.current_streak = 0
    await session.flush()
    return participation


async def list_active(session: AsyncSession, challenge_id: int) -> list[Participation]:
    return list(
        await session.scalars(
            select(Participation)
            .where(
                Participation.challenge_id == challenge_id,
                Participation.status == ParticipationStatus.ACTIVE,
            )
            .options(joinedload(Participation.user))
            .order_by(Participation.id)
        )
    )


async def count_active(session: AsyncSession, challenge_id: int) -> int:
    return len(await list_active(session, challenge_id))


async def set_streaks(
    session: AsyncSession, participation: Participation, current: int, best: int
) -> None:
    participation.current_streak = current
    participation.best_streak = max(best, participation.best_streak)
    await session.flush()
