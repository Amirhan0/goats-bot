"""aiogram обрабатывает апдейты параллельно — два сообщения от одного
нового пользователя не должны ронять обработчик."""

from __future__ import annotations

import asyncio

from sqlalchemy import func, select

from bot.db.models import User
from bot.repositories import users as users_repo


async def _touch(sessionmaker, telegram_id: int) -> int:
    async with sessionmaker() as session:
        user = await users_repo.get_or_create(
            session, telegram_id=telegram_id, username="p1kato", first_name="Пик"
        )
        await session.commit()
        return user.id


async def test_concurrent_first_messages_create_one_user(sessionmaker):
    ids = await asyncio.gather(*(_touch(sessionmaker, 769273084) for _ in range(5)))

    assert len(set(ids)) == 1
    async with sessionmaker() as session:
        total = await session.scalar(select(func.count(User.id)))
    assert total == 1


async def test_existing_user_profile_is_refreshed(session):
    await users_repo.get_or_create(
        session, telegram_id=555, username="old", first_name="Старое"
    )
    await session.commit()

    user = await users_repo.get_or_create(
        session, telegram_id=555, username="new", first_name="Новое"
    )

    assert (user.username, user.first_name) == ("new", "Новое")
