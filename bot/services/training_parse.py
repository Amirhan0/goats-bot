"""Разбор тренировки из обычного текста.

«Завтра в 19:30, Центральный стадион, интервальная 6×400» → дата, время,
место, тип, описание. Чистые функции: ни БД, ни сети — всё проверяется тестами.

Разбор намеренно снисходительный: он лишь заполняет черновик, а админ видит
предпросмотр и может поправить любое поле до публикации.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

MONTHS = {
    "янв": 1, "фев": 2, "мар": 3, "апр": 4, "мая": 5, "май": 5, "июн": 6,
    "июл": 7, "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12,
}

WEEKDAYS = {
    "понедельник": 0, "пн": 0,
    "вторник": 1, "вт": 1,
    "среда": 2, "среду": 2, "ср": 2,
    "четверг": 3, "чт": 3,
    "пятница": 4, "пятницу": 4, "пт": 4,
    "суббота": 5, "субботу": 5, "сб": 5,
    "воскресенье": 6, "вс": 6,
}

# Типы, которые бот узнаёт в тексте, — чтобы отделить «что» от подробностей.
KNOWN_TYPES = (
    "интервальная", "интервалы", "темповая", "темпо", "длительная", "лонг",
    "кросс", "восстановительная", "фартлек", "офп", "сбм", "забег",
    "старт", "разминка", "техника", "горки", "прогрессия",
)

_TIME_RE = re.compile(r"(?<!\d)([01]?\d|2[0-3])\s*[:.\-]\s*([0-5]\d)(?!\d)")
_TIME_HOUR_RE = re.compile(r"\bв\s+([01]?\d|2[0-3])(?!\s*[:.\-]?\d)\b", re.IGNORECASE)
_DMY_RE = re.compile(r"(?<!\d)(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?(?!\d)")
_DAY_MONTH_RE = re.compile(r"(?<!\d)(\d{1,2})\s+([а-яё]{3,})", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ParsedTraining:
    """day и clock отдаются отдельно: в пошаговом мастере дата приходит без
    времени, и требовать их только вместе — значит не принять вообще ничего."""

    start_at: datetime | None
    day: date | None = None
    clock: time | None = None
    location: str = ""
    training_type: str = ""
    description: str = ""

    @property
    def missing(self) -> tuple[str, ...]:
        gaps = []
        if self.start_at is None:
            gaps.append("дата и время")
        if not self.location:
            gaps.append("место")
        if not self.training_type and not self.description:
            gaps.append("тип тренировки")
        return tuple(gaps)


def _find_time(text: str) -> tuple[time, str] | None:
    match = _TIME_RE.search(text)
    if match:
        found = time(int(match.group(1)), int(match.group(2)))
        return found, text[: match.start()] + " " + text[match.end() :]
    match = _TIME_HOUR_RE.search(text)
    if match:
        return time(int(match.group(1)), 0), text[: match.start()] + " " + text[match.end() :]
    return None


def _find_date(text: str, today: date) -> tuple[date, str] | None:
    lowered = text.lower()

    for word, shift in (("послезавтра", 2), ("завтра", 1), ("сегодня", 0)):
        pos = lowered.find(word)
        if pos != -1:
            return today + timedelta(days=shift), text[:pos] + " " + text[pos + len(word) :]

    match = _DMY_RE.search(text)
    if match:
        day, month = int(match.group(1)), int(match.group(2))
        year = int(match.group(3) or today.year)
        if year < 100:
            year += 2000
        found = _safe_date(year, month, day)
        if found:
            return found, text[: match.start()] + " " + text[match.end() :]

    match = _DAY_MONTH_RE.search(text)
    if match:
        month = MONTHS.get(match.group(2)[:3].lower())
        if month:
            found = _safe_date(today.year, month, int(match.group(1)))
            if found:
                # «5 января», сказанное в декабре, — это следующий год.
                if found < today:
                    found = _safe_date(today.year + 1, month, int(match.group(1))) or found
                return found, text[: match.start()] + " " + text[match.end() :]

    for word, weekday in WEEKDAYS.items():
        if re.search(rf"\b{word}\b", lowered):
            ahead = (weekday - today.weekday()) % 7 or 7
            pos = lowered.find(word)
            return today + timedelta(days=ahead), text[:pos] + " " + text[pos + len(word) :]

    return None


# После вырезания даты и времени в куске остаются предлоги: «завтра в 19:30»
# превращается в « в ». Такой хвост не должен занять место локации.
_FILLER = {"в", "во", "на", "к", "ко", "и", "у", "с", "со", "до", "часов", "час", "ч"}


def _is_noise(chunk: str) -> bool:
    words = [w.lower().strip(".,;:-—()") for w in chunk.split()]
    words = [w for w in words if w]
    return all(w in _FILLER for w in words)


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _split_type(chunk: str) -> tuple[str, str]:
    """Отделяет «интервальная» от «6×400»: тип — известное слово в начале."""
    words = chunk.split()
    if not words:
        return "", ""
    first = words[0].lower().strip(".,")
    if first.startswith(KNOWN_TYPES):
        head = words[:2] if len(words) > 1 and words[1].lower() in {"тренировка", "бег"} else words[:1]
        return " ".join(head).capitalize(), " ".join(words[len(head) :]).strip()
    return chunk.strip(), ""


def parse(text: str, tz: ZoneInfo, now: datetime) -> ParsedTraining:
    """now нужен, чтобы «завтра» считалось от текущего дня в зоне клуба."""
    today = now.astimezone(tz).date()
    chunks = [c.strip() for c in re.split(r"[,;\n]", text) if c.strip()]
    if not chunks:
        return ParsedTraining(start_at=None)

    head = chunks[0]
    found_time = _find_time(head)
    clock, head = found_time if found_time else (None, head)
    found_date = _find_date(head, today)
    day, head = found_date if found_date else (None, head)

    # Дата и время могли оказаться в разных кусках: «28 августа, в 19:30, стадион».
    rest = chunks[1:]
    if clock is None:
        for i, chunk in enumerate(rest):
            found = _find_time(chunk)
            if found:
                clock, rest[i] = found
                break
    if day is None:
        for i, chunk in enumerate(rest):
            found = _find_date(chunk, today)
            if found:
                day, rest[i] = found
                break

    start_at = None
    if day is not None and clock is not None:
        start_at = datetime.combine(day, clock, tzinfo=tz)
    elif clock is not None:
        # Время без даты — ближайший день, когда это время ещё не прошло.
        candidate = datetime.combine(today, clock, tzinfo=tz)
        start_at = candidate if candidate > now.astimezone(tz) else candidate + timedelta(days=1)

    leftovers = [c.strip(" ,.;-—") for c in [head, *rest] if not _is_noise(c)]
    location = leftovers[0] if leftovers else ""
    training_type, description = _split_type(leftovers[1]) if len(leftovers) > 1 else ("", "")
    if len(leftovers) > 2:
        description = " ".join([description, *leftovers[2:]]).strip()

    return ParsedTraining(
        start_at=start_at,
        day=day,
        clock=clock,
        location=location,
        training_type=training_type,
        description=description,
    )
