from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Chat, TelegramObject

from bot.config import Settings, settings_for_club
from bot.db.models import Club
from bot.repositories import clubs as clubs_repo


class ClubMiddleware(BaseMiddleware):
    """Определяет клуб, к которому относится апдейт, и наводит на него настройки.

    Чат берём из data["event_chat"], который кладёт сам aiogram. Проверять
    isinstance(event, Message) здесь нельзя: на уровне update в мидлварь
    приходит Update, а не вложенное сообщение, — из-за этого клуб молча
    не находился и все группы работали по настройкам из .env.

    В группе клуб определяется по chat_id, в личке — по роли человека
    (см. clubs_repo.for_user_in_dm). Клуб может быть None: бота добавили
    в группу, которую ещё не завели через /newclub, — там он молчит.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        club: Club | None = None
        session = data.get("session")
        chat: Chat | None = data.get("event_chat")

        if session is not None and chat is not None:
            if chat.type == "private":
                user = data.get("user")
                tg_user = data.get("event_from_user")
                if user is not None and tg_user is not None:
                    club = await clubs_repo.for_user_in_dm(session, tg_user.id, user.id)
            else:
                club = await clubs_repo.get_by_chat(session, chat.id)

        data["club"] = club
        if club is not None:
            # Подменяем settings на клубную копию: весь код ниже спрашивает
            # «куда постить» и «кто судья» именно у неё.
            base: Settings | None = data.get("settings")
            if base is not None:
                data["settings"] = settings_for_club(base, club)
        return await handler(event, data)
