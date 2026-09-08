"""Серии считаются как функция от истории approved-дней, а не инкрементом.

Поля Participation.current_streak / best_streak — это кэш: любой вердикт,
откат вердикта или закрытие дня пересчитывают их отсюда. Благодаря этому
зачёт задним числом (судья принял pending уже после закрытия дня) корректно
восстанавливает серию, а не просто прибавляет единицу.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

APPROVED = "✅"
MISSED = "❌"
PENDING = "⏳"
OPEN = "⬜"


def compute_current_streak(approved_days: Iterable[int], current_day: int) -> int:
    """Серия жива, если зачтён сегодняшний день или вчерашний
    (сегодня ещё можно сдать — серия не считается прерванной)."""
    days = set(approved_days)
    if not days:
        return 0

    anchor = current_day if current_day in days else current_day - 1
    if anchor not in days:
        return 0

    length = 0
    while anchor in days:
        length += 1
        anchor -= 1
    return length


def compute_best_streak(approved_days: Iterable[int]) -> int:
    days = sorted(set(approved_days))
    if not days:
        return 0

    best = current = 1
    for prev, day in zip(days, days[1:], strict=False):
        current = current + 1 if day == prev + 1 else 1
        best = max(best, current)
    return best


def compute_streaks(approved_days: Iterable[int], current_day: int) -> tuple[int, int]:
    days = list(approved_days)
    return compute_current_streak(days, current_day), compute_best_streak(days)


def missed_days(approved_days: Iterable[int], join_day: int, last_closed_day: int) -> list[int]:
    """Закрытые дни от вступления до last_closed_day включительно без зачёта."""
    days = set(approved_days)
    if last_closed_day < join_day:
        return []
    return [d for d in range(join_day, last_closed_day + 1) if d not in days]


@dataclass(frozen=True, slots=True)
class Completion:
    approved: int
    total: int

    @property
    def percent(self) -> int:
        return round(self.approved / self.total * 100) if self.total else 0


def compute_completion(approved_count: int, join_day: int, current_day: int) -> Completion:
    """Знаменатель включает текущий день — как в карточке судьи (11/12)."""
    total = max(0, current_day - join_day + 1)
    return Completion(approved=approved_count, total=total)


def calendar_string(
    approved_days: Iterable[int],
    pending_days: Iterable[int],
    join_day: int,
    current_day: int,
    max_len: int = 30,
) -> str:
    """Строка вида ✅✅❌⬜✅ за последние max_len дней участия."""
    approved = set(approved_days)
    pending = set(pending_days)
    first = max(join_day, current_day - max_len + 1)

    cells: list[str] = []
    for day in range(first, current_day + 1):
        if day in approved:
            cells.append(APPROVED)
        elif day in pending:
            cells.append(PENDING)
        elif day == current_day:
            cells.append(OPEN)
        else:
            cells.append(MISSED)
    return "".join(cells)
