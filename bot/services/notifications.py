"""Личные сообщения от бота. Массовых рассылок нет: бот не может написать
первым тому, кто не нажимал /start, — всё общее уходит постом в беседу
(см. services/announce.py). Здесь остаётся только адресная отправка админу."""

from __future__ import annotations

import logging

from aiogram import Bot

from bot.utils import tg_retry

logger = logging.getLogger(__name__)


async def notify(bot: Bot, chat_id: int, text: str, **kwargs) -> bool:
    result = await tg_retry.call_safe(bot.send_message, chat_id=chat_id, text=text, **kwargs)
    return result is not None
