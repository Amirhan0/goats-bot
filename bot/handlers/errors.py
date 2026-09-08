from __future__ import annotations

import logging

from aiogram import Router
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import ErrorEvent

from bot import texts

logger = logging.getLogger(__name__)

router = Router(name="errors")

# Подключается последним: сюда попадают колбэки, которые не разобрал ни один
# обработчик. Без него у пользователя вечно крутится спиннер, а в логах пусто.
fallback_router = Router(name="fallback")


@fallback_router.callback_query()
async def on_unhandled_callback(callback) -> None:  # noqa: ANN001
    logger.warning(
        "Необработанный колбэк: data=%r от %s",
        callback.data,
        callback.from_user.id if callback.from_user else None,
    )
    await callback.answer()


@router.errors()
async def on_error(event: ErrorEvent) -> bool:
    """Последний рубеж: ни один апдейт не должен ронять процесс.
    Возврат True говорит aiogram, что ошибка обработана."""
    exception = event.exception

    if isinstance(exception, TelegramForbiddenError):
        logger.info("Пользователь заблокировал бота: %s", exception)
        return True
    if isinstance(exception, TelegramRetryAfter):
        logger.warning("Flood control: %s", exception)
        return True

    logger.exception("Необработанная ошибка при обработке апдейта", exc_info=exception)

    update = event.update
    message = getattr(update, "message", None)
    callback = getattr(update, "callback_query", None)

    try:
        if callback is not None:
            await callback.answer(texts.GENERIC_ERROR, show_alert=True)
        elif message is not None and message.chat.type == "private":
            await message.answer(texts.GENERIC_ERROR)
    except Exception:  # noqa: BLE001
        logger.debug("Не удалось сообщить пользователю об ошибке")

    return True
