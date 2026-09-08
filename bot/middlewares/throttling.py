from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from bot import texts


class VideoNoteThrottleMiddleware(BaseMiddleware):
    """Флуд-контроль вместо лимита попыток: не чаще одного кружка в N секунд.
    Хранится в памяти — запись в БД для отбитого спама не создаётся."""

    def __init__(self, cooldown_sec: int) -> None:
        self.cooldown = cooldown_sec
        self._last: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or event.video_note is None:
            return await handler(event, data)
        if event.from_user is None:
            return await handler(event, data)

        now = time.monotonic()
        previous = self._last.get(event.from_user.id)
        if previous is not None and now - previous < self.cooldown:
            wait = int(self.cooldown - (now - previous)) + 1
            await event.answer(texts.COOLDOWN.format(seconds=wait))
            return None

        self._last[event.from_user.id] = now
        return await handler(event, data)
