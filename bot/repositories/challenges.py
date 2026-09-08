from __future__ import annotations

from datetime import date

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Challenge


async def get_active(
    session: AsyncSession, is_test: bool, club_id: int | None = None
) -> Challenge | None:
    """Активный челлендж клуба. club_id=None — старое поведение «один на всех»,
    оно осталось для тестов и для установок, где клуб ещё не заведён."""
    stmt = select(Challenge).where(
        Challenge.is_active.is_(True), Challenge.is_test.is_(is_test)
    )
    if club_id is not None:
        stmt = stmt.where(Challenge.club_id == club_id)
    return await session.scalar(stmt.order_by(Challenge.id.desc()))


async def get_by_id(session: AsyncSession, challenge_id: int) -> Challenge | None:
    return await session.get(Challenge, challenge_id)


async def create(
    session: AsyncSession,
    *,
    title: str,
    start_date: date,
    is_test: bool,
    description: str = "",
    rules_text: str = "",
    end_date: date | None = None,
    min_duration_sec: int = 58,
    max_duration_sec: int = 600,
    club_id: int | None = None,
) -> Challenge:
    challenge = Challenge(
        club_id=club_id,
        title=title,
        description=description,
        rules_text=rules_text,
        start_date=start_date,
        end_date=end_date,
        min_duration_sec=min_duration_sec,
        max_duration_sec=max_duration_sec,
        is_test=is_test,
        is_active=True,
    )
    session.add(challenge)
    await session.flush()
    return challenge


async def deactivate_others(
    session: AsyncSession, is_test: bool, keep_id: int, club_id: int | None = None
) -> None:
    """Гасим только соседей по клубу: у чужой группы свой активный челлендж,
    и трогать его нельзя."""
    stmt = update(Challenge).where(
        Challenge.is_test.is_(is_test),
        Challenge.id != keep_id,
        Challenge.is_active.is_(True),
    )
    if club_id is not None:
        stmt = stmt.where(Challenge.club_id == club_id)
    await session.execute(stmt.values(is_active=False))


async def list_test(session: AsyncSession) -> list[Challenge]:
    return list(await session.scalars(select(Challenge).where(Challenge.is_test.is_(True))))
