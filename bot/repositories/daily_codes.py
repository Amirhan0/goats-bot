from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import DailyCode


async def get(session: AsyncSession, challenge_id: int, day: date) -> DailyCode | None:
    return await session.scalar(
        select(DailyCode).where(DailyCode.challenge_id == challenge_id, DailyCode.date == day)
    )


async def upsert(
    session: AsyncSession, challenge_id: int, day: date, code: str, is_manual: bool = False
) -> DailyCode:
    existing = await get(session, challenge_id, day)
    if existing is not None:
        existing.code = code
        existing.is_manual = is_manual
        await session.flush()
        return existing

    daily = DailyCode(challenge_id=challenge_id, date=day, code=code, is_manual=is_manual)
    session.add(daily)
    await session.flush()
    return daily


async def recent_codes(
    session: AsyncSession, challenge_id: int, day: date, window_days: int
) -> set[str]:
    """Слова за последние window_days — чтобы не повторяться."""
    since = day - timedelta(days=window_days)
    rows = await session.scalars(
        select(DailyCode.code).where(
            DailyCode.challenge_id == challenge_id,
            DailyCode.date > since,
        )
    )
    return {c.lower() for c in rows}
