from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.enums import Role
from bot.db.models import User


async def get_by_telegram_id(session: AsyncSession, telegram_id: int) -> User | None:
    return await session.scalar(select(User).where(User.telegram_id == telegram_id))


async def get_by_id(session: AsyncSession, user_id: int) -> User | None:
    return await session.get(User, user_id)


async def get_or_create(
    session: AsyncSession,
    telegram_id: int,
    username: str | None,
    first_name: str,
    role: Role = Role.PARTICIPANT,
) -> User:
    user = await get_by_telegram_id(session, telegram_id)
    if user is None:
        # aiogram обрабатывает апдейты параллельно, поэтому два сообщения от
        # одного нового пользователя легко приходят одновременно и оба видят
        # «пользователя нет». Вставку делаем в SAVEPOINT: проигравший ловит
        # нарушение уникальности, откатывает только его и перечитывает строку.
        try:
            async with session.begin_nested():
                user = User(
                    telegram_id=telegram_id,
                    username=username,
                    first_name=first_name or "",
                    role=role,
                )
                session.add(user)
                await session.flush()
            return user
        except IntegrityError:
            user = await get_by_telegram_id(session, telegram_id)
            if user is None:  # чужой коммит ещё не виден — отдать нечего
                raise

    # Профиль в Telegram мог измениться — держим его актуальным.
    if user.username != username:
        user.username = username
    if first_name and user.first_name != first_name:
        user.first_name = first_name
    if user.role != role:
        user.role = role
    return user


async def set_blocked(
    session: AsyncSession, telegram_id: int, blocked: bool, reason: str | None = None
) -> bool:
    result = await session.execute(
        update(User)
        .where(User.telegram_id == telegram_id)
        .values(is_blocked=blocked, block_reason=reason if blocked else None)
    )
    return bool(result.rowcount)


async def list_by_ids(session: AsyncSession, user_ids: list[int]) -> list[User]:
    if not user_ids:
        return []
    return list(await session.scalars(select(User).where(User.id.in_(user_ids))))


async def map_by_telegram_ids(
    session: AsyncSession, telegram_ids: tuple[int, ...]
) -> dict[int, User]:
    """Словарь telegram_id → User. Кого бот ещё не видел, в словаре не будет:
    судью могли вписать в .env раньше, чем он написал боту."""
    if not telegram_ids:
        return {}
    rows = await session.scalars(select(User).where(User.telegram_id.in_(telegram_ids)))
    return {u.telegram_id: u for u in rows}
