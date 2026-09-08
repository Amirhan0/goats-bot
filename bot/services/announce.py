"""Ответы бота в общей беседе.

Отдельного канала для зачтённых кружков нет: кружок уже лежит в беседе на
виду у всех, поэтому «публикация» — это реплай бота на него с вердиктом.
Id реплая храним, чтобы удалить его при откате вердикта.
"""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.types import ReactionTypeEmoji
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.config import Settings
from bot.db.models import Submission
from bot.repositories import submissions as submissions_repo
from bot.utils import tg_retry

logger = logging.getLogger(__name__)

# Telegram разрешает реакции только из фиксированного набора: ✅ / ❌ / ⏳
# в него не входят, 🐐 тоже (API отвечает REACTION_INVALID). Поэтому козёл
# живёт в текстах, а статус на кружке показывают разрешённые эмодзи.
REACTION_APPROVED = "🏆"  # кружок в зачёте
REACTION_REJECTED = "👎"  # зачёт отменён


async def set_reaction(
    bot: Bot, settings: Settings, submission: Submission, emoji: str
) -> bool:
    """Реакция вместо сообщения — способ не превратить беседу в ленту бота.
    Беседа может ограничивать набор реакций, поэтому провал ожидаем:
    вызывающий откатывается на текст."""
    if not settings.use_reactions:
        return False
    result = await tg_retry.call_safe(
        bot.set_message_reaction,
        chat_id=submission.chat_id or settings.participants_chat_id,
        message_id=submission.message_id,
        reaction=[ReactionTypeEmoji(emoji=emoji)],
    )
    return result is not None


async def mark_accepted(bot: Bot, settings: Settings, submission: Submission) -> bool:
    """При 20 участниках убирает два десятка сообщений «принято» в день.

    Сразу 🏆, а не «судья ещё не смотрел»: кружок зачтён в момент отправки,
    и ждать судью человеку незачем. Если зачёт потом отменят — станет 👎.
    """
    return await set_reaction(bot, settings, submission, REACTION_APPROVED)


async def reply_to_submission(
    bot: Bot, settings: Settings, submission: Submission, text: str
) -> int | None:
    """Реплай на сам кружок: участник получает уведомление и видит,
    к какой именно сдаче относится ответ."""
    # В форуме реплай без message_thread_id улетает в общую ветку.
    sent = await tg_retry.call_safe(
        bot.send_message,
        chat_id=submission.chat_id or settings.participants_chat_id,
        text=text,
        reply_to_message_id=submission.message_id,
        **settings.participants_thread,
    )
    return sent.message_id if sent is not None else None


async def announce_verdict(
    bot: Bot,
    session: AsyncSession,
    settings: Settings,
    submission: Submission,
    *,
    approve: bool,
    streak: int,
    reason_text: str | None,
    deadline: str,
    day_over: bool,
    judge_name: str,
) -> None:
    user = submission.participation.user
    if approve:
        text = texts.verdict_approved(
            user.mention_html, submission.challenge_day, streak, judge_name
        )
    else:
        text = texts.verdict_rejected(
            user.mention_html,
            submission.challenge_day,
            reason_text or "без причины",
            deadline,
            day_over,
            judge_name,
        )

    message_id = await reply_to_submission(bot, settings, submission, text)
    if message_id is not None:
        await submissions_repo.set_verdict_message(session, submission.id, message_id)


async def remove_verdict_message(
    bot: Bot, settings: Settings, submission: Submission
) -> None:
    if not submission.verdict_message_id:
        return
    await tg_retry.call_safe(
        bot.delete_message,
        chat_id=submission.chat_id or settings.participants_chat_id,
        message_id=submission.verdict_message_id,
    )


async def post_to_chat(bot: Bot, settings: Settings, text: str, **kwargs) -> None:
    """Общий пост в беседу: слово дня, напоминание, итоги дня."""
    await tg_retry.call_safe(
        bot.send_message,
        chat_id=settings.participants_chat_id,
        text=text,
        **settings.participants_thread,
        **kwargs,
    )
