"""Слово дня.

Слово на день D генерируется сразу после закрытия предыдущего дня, а
публикуется в 09:00. Иначе между сменой суток и утренним постом сдавать
уже можно, а слова ещё нет. Дополнительно есть ленивый fallback: любой запрос слова создаёт его,
если записи нет.
"""

from __future__ import annotations

import logging
import random
from datetime import date
from functools import lru_cache
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Settings
from bot.db.models import Challenge
from bot.repositories import daily_codes as codes_repo

logger = logging.getLogger(__name__)

FALLBACK_WORDS = ("абрикос", "маяк", "варежка", "компас", "сугроб", "теплица")


@lru_cache(maxsize=4)
def load_words(path: Path) -> tuple[str, ...]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        logger.error("Не удалось прочитать словарь %s, использую запасной список", path)
        return FALLBACK_WORDS

    words = tuple(
        dict.fromkeys(
            line.strip().lower()
            for line in raw.splitlines()
            if line.strip() and not line.startswith("#")
        )
    )
    if not words:
        logger.error("Словарь %s пуст, использую запасной список", path)
        return FALLBACK_WORDS
    return words


def pick_word(words: tuple[str, ...], exclude: set[str]) -> str:
    """Случайное слово, не встречавшееся в окне без повторов.
    Если словарь исчерпан — берём из всего словаря."""
    pool = [w for w in words if w not in exclude]
    return random.choice(pool or list(words))


async def ensure_code(
    session: AsyncSession, challenge: Challenge, day: date, settings: Settings
) -> str | None:
    if not settings.daily_code_enabled:
        return None

    existing = await codes_repo.get(session, challenge.id, day)
    if existing is not None:
        return existing.code

    words = load_words(settings.words_path)
    recent = await codes_repo.recent_codes(
        session, challenge.id, day, settings.code_no_repeat_days
    )
    word = pick_word(words, recent)
    await codes_repo.upsert(session, challenge.id, day, word, is_manual=False)
    logger.info("Слово дня на %s: %s", day, word)
    return word


async def get_code(
    session: AsyncSession, challenge: Challenge, day: date, settings: Settings
) -> str | None:
    if not settings.daily_code_enabled:
        return None
    existing = await codes_repo.get(session, challenge.id, day)
    return existing.code if existing else None


async def set_manual_code(
    session: AsyncSession, challenge: Challenge, day: date, word: str
) -> str:
    await codes_repo.upsert(session, challenge.id, day, word.strip().lower(), is_manual=True)
    return word.strip().lower()
