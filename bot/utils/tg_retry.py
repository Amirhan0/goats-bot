"""Ретраи вокруг вызовов Bot API. Сеть моргает — процесс от этого падать не должен."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")

MAX_ATTEMPTS = 3


async def call(func: Callable[..., Awaitable[T]], /, *args: Any, **kwargs: Any) -> T:
    """Повторяет вызов при сетевых ошибках и 429. Логические ошибки
    (bad request, forbidden) пробрасываются сразу — ретрай их не починит."""
    last_error: Exception | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return await func(*args, **kwargs)
        except TelegramRetryAfter as exc:
            last_error = exc
            logger.warning("429 от Telegram, ждём %s сек", exc.retry_after)
            await asyncio.sleep(exc.retry_after + 1)
        except (TelegramNetworkError, TelegramServerError) as exc:
            last_error = exc
            delay = 2 ** (attempt - 1)
            logger.warning("Сетевая ошибка (%s), попытка %s/%s", exc, attempt, MAX_ATTEMPTS)
            await asyncio.sleep(delay)

    assert last_error is not None
    raise last_error


async def call_safe(func: Callable[..., Awaitable[T]], /, *args: Any, **kwargs: Any) -> T | None:
    """Как call(), но None вместо исключения: для «желательных, но не
    критичных» вызовов — уведомлений, удаления постов, редактирования карточек."""
    try:
        return await call(func, *args, **kwargs)
    except TelegramForbiddenError:
        logger.info("Пользователь заблокировал бота или чат недоступен")
    except TelegramBadRequest as exc:
        # Перерисовка поста без изменений — штатная ситуация, не ошибка.
        if "message is not modified" in str(exc):
            logger.debug("Сообщение не изменилось, правка не нужна")
        else:
            logger.warning("Bad request: %s", exc)
    except Exception:  # noqa: BLE001 — фон не должен ронять хендлер
        logger.exception("Не удалось выполнить запрос к Telegram")
    return None
