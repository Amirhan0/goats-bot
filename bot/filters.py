from __future__ import annotations

from typing import Any

from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject

from bot.config import Settings


def _actor_id(event: TelegramObject) -> int | None:
    user = getattr(event, "from_user", None)
    return user.id if user is not None else None


class IsAdmin(BaseFilter):
    async def __call__(self, event: TelegramObject, **data: Any) -> bool:
        settings: Settings | None = data.get("settings")
        actor = _actor_id(event)
        return settings is not None and actor is not None and settings.is_admin(actor)


class IsJudge(BaseFilter):
    """Право судить определяется списком JUDGE_IDS, а не членством в группе."""

    async def __call__(self, event: TelegramObject, **data: Any) -> bool:
        settings: Settings | None = data.get("settings")
        actor = _actor_id(event)
        return settings is not None and actor is not None and settings.is_judge(actor)


def _chat_id(event: TelegramObject) -> int | None:
    chat = getattr(event, "chat", None) or getattr(
        getattr(event, "message", None), "chat", None
    )
    return chat.id if chat is not None else None


class InJudgesChat(BaseFilter):
    async def __call__(self, event: TelegramObject, **data: Any) -> bool:
        settings: Settings | None = data.get("settings")
        return settings is not None and _chat_id(event) == settings.judges_chat_id


class InParticipantsChat(BaseFilter):
    """Кружки принимаются только из беседы челленджа, а в форуме — только
    из своего топика. Иначе кружок, брошенный в ветку тренировок, тоже
    уехал бы в зачёт."""

    async def __call__(self, event: TelegramObject, **data: Any) -> bool:
        settings: Settings | None = data.get("settings")
        if settings is None:
            return False
        thread = getattr(event, "message_thread_id", None)
        return settings.in_participants_thread(_chat_id(event) or 0, thread)
