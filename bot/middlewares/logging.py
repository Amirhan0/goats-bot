from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

logger = logging.getLogger("bot.updates")

SLOW_UPDATE_SEC = 3.0


class UpdateLoggingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        started = time.monotonic()
        update_id = event.update_id if isinstance(event, Update) else None
        tg_user = data.get("event_from_user")
        try:
            return await handler(event, data)
        finally:
            elapsed = time.monotonic() - started
            level = logging.WARNING if elapsed > SLOW_UPDATE_SEC else logging.DEBUG
            logger.log(
                level,
                "update=%s user=%s обработан за %.2f сек",
                update_id,
                getattr(tg_user, "id", None),
                elapsed,
            )
