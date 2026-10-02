from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Challenge, Club, Participation


async def get(session: AsyncSession, club_id: int) -> Club | None:
    return await session.get(Club, club_id)


async def get_by_chat(session: AsyncSession, chat_id: int) -> Club | None:
    return await session.scalar(
        select(Club).where(Club.chat_id == chat_id, Club.is_active.is_(True))
    )


async def list_active(session: AsyncSession) -> list[Club]:
    return list(
        await session.scalars(
            select(Club).where(Club.is_active.is_(True)).order_by(Club.id)
        )
    )


async def create(
    session: AsyncSession,
    *,
    title: str,
    chat_id: int,
    participants_thread_id: int = 0,
    trainings_thread_id: int = 0,
    checkins_thread_id: int = 0,
    judges_chat_id: int = 0,
    judge_ids: list[int] | None = None,
    admin_ids: list[int] | None = None,
    challenge_task: str = "",
    prizes: str = "",
    challenge_enabled: bool = True,
) -> Club:
    club = Club(
        title=title,
        chat_id=chat_id,
        participants_thread_id=participants_thread_id,
        trainings_thread_id=trainings_thread_id,
        checkins_thread_id=checkins_thread_id,
        judges_chat_id=judges_chat_id,
        judge_ids=judge_ids or [],
        admin_ids=admin_ids or [],
        challenge_task=challenge_task,
        prizes=prizes,
        challenge_enabled=challenge_enabled,
    )
    session.add(club)
    await session.flush()
    return club


async def for_user_in_dm(session: AsyncSession, telegram_id: int, user_pk: int) -> Club | None:
    """Какой клуб человек имеет в виду, когда пишет боту в личку.

    Чата, по которому можно определить клуб, в личке нет, поэтому идём от
    роли: сначала где он админ, потом где судья, потом где участвует.
    Если клуб один — вопрос не стоит вовсе, а это самый частый случай.
    """
    clubs = await list_active(session)
    if len(clubs) <= 1:
        return clubs[0] if clubs else None

    for predicate in (lambda c: c.is_admin(telegram_id), lambda c: c.is_judge(telegram_id)):
        owned = [c for c in clubs if predicate(c)]
        if owned:
            return owned[0]

    club_id = await session.scalar(
        select(Challenge.club_id)
        .join(Participation, Participation.challenge_id == Challenge.id)
        .where(Participation.user_id == user_pk, Challenge.is_active.is_(True))
        .limit(1)
    )
    if club_id is not None:
        return next((c for c in clubs if c.id == club_id), None)
    return None
