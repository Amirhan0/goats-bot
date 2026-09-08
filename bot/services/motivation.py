"""Похвала и цитата в ответ на зачтённый кружок.

Цитаты лежат в data/quotes.json, чтобы менять их без правки кода и деплоя.
Повторы гасятся окном последних выданных: пока не пройдёт две трети пула,
цитата не вернётся. Окно живёт в памяти и сбрасывается при перезапуске —
для «не повторяться в пределах вечера» этого достаточно, а тащить ради
этого таблицу в БД смысла нет.
"""

from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

PRAISE = (
    "красава",
    "хорош",
    "машина",
    "красавчик",
    "зверь",
    "так держать",
    "не сдаёшься",
    "уважение",
    "по-мужски",
    "чётко",
)


@dataclass(frozen=True, slots=True)
class Quote:
    text: str
    author: str | None = None

    def render(self) -> str:
        return f"{self.text} — {self.author}" if self.author else self.text


FALLBACK_QUOTES = (
    Quote("Регулярность бьёт интенсивность."),
    Quote("Единственная плохая тренировка — та, которой не было."),
)


@lru_cache(maxsize=4)
def load_quotes(path: Path) -> tuple[Quote, ...]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Не удалось прочитать цитаты %s (%s), беру запасные", path, exc)
        return FALLBACK_QUOTES

    quotes: list[Quote] = []
    for item in raw:
        text = (item.get("text") or "").strip() if isinstance(item, dict) else str(item).strip()
        if not text:
            continue
        author = item.get("author") if isinstance(item, dict) else None
        quotes.append(Quote(text, (author or "").strip() or None))

    if not quotes:
        logger.error("В %s нет ни одной цитаты, беру запасные", path)
        return FALLBACK_QUOTES
    return tuple(quotes)


def _pick_fresh(items: tuple, recent: list[int]) -> int:
    """Выбираем из тех, что давно не выпадали. Окно — две трети пула:
    достаточно, чтобы не приедалось, и не настолько жёстко, чтобы выбор
    стал предсказуемым."""
    window = max(1, len(items) * 2 // 3)
    seen = set(recent[-window:])
    pool = [i for i in range(len(items)) if i not in seen] or list(range(len(items)))
    index = random.choice(pool)
    recent.append(index)
    del recent[:-window]
    return index


_recent_quotes: list[int] = []
_recent_praise: list[int] = []


def pick_quote(path: Path) -> str:
    quotes = load_quotes(path)
    return quotes[_pick_fresh(quotes, _recent_quotes)].render()


def pick_praise() -> str:
    return PRAISE[_pick_fresh(PRAISE, _recent_praise)]


# Круглые числа, на которых стоит отметить человека отдельно.
MILESTONES: dict[int, str] = {
    5: "🖐 Пятый кружок — привычка зарождается.",
    10: "🔟 Десять кружков. Уже не случайность.",
    25: "💪 Двадцать пять. Это уже характер.",
    50: "🏅 Полтинник! Половина сотни позади.",
    100: "💯 СОТНЯ КРУЖКОВ. Снимаем шляпу.",
    200: "🚀 Двести. Это уже образ жизни.",
    365: "👑 Год кружков. Легенда.",
}


def milestone(total_circles: int) -> str | None:
    """Отдельная строка на круглых числах — редкая, поэтому не приедается."""
    return MILESTONES.get(total_circles)
