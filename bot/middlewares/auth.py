from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot import texts
from bot.config import Settings
from bot.db.enums import Role
from bot.repositories import users as users_repo


class UserMiddleware(BaseMiddleware):
    """Кладёт в data актуального User. Роль всегда берётся из .env —
    членство в группе судей само по себе прав не даёт."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        if tg_user is None or tg_user.is_bot:
            return await handler(event, data)

        role = Role.PARTICIPANT
        if self.settings.is_admin(tg_user.id):
            role = Role.ADMIN
        elif self.settings.is_judge(tg_user.id):
            role = Role.JUDGE

        session = data["session"]
        user = await users_repo.get_or_create(
            session,
            telegram_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name or "",
            role=role,
        )
        data["user"] = user
        data["settings"] = self.settings

        if user.is_blocked:
            await session.commit()
            if isinstance(event, Message) and event.chat.type == "private":
                await event.answer(texts.BLOCKED)
            elif isinstance(event, CallbackQuery):
                await event.answer(texts.BLOCKED, show_alert=True)
            return None

        return await handler(event, data)
