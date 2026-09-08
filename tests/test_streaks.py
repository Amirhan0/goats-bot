from __future__ import annotations

from bot.services.streaks import (
    calendar_string,
    compute_best_streak,
    compute_completion,
    compute_current_streak,
    compute_streaks,
    missed_days,
)


def test_empty_history() -> None:
    assert compute_current_streak([], 5) == 0
    assert compute_best_streak([]) == 0


def test_streak_counted_from_today() -> None:
    assert compute_current_streak([1, 2, 3, 4, 5], 5) == 5


def test_streak_alive_if_yesterday_done() -> None:
    """Сегодня ещё можно сдать — серия не считается прерванной."""
    assert compute_current_streak([1, 2, 3, 4], 5) == 4


def test_streak_broken_after_two_days_without_approval() -> None:
    assert compute_current_streak([1, 2, 3], 5) == 0


def test_gap_resets_current_streak() -> None:
    assert compute_current_streak([1, 2, 5, 6], 6) == 2


def test_best_streak_survives_break() -> None:
    days = [1, 2, 3, 4, 5, 8, 9]
    assert compute_best_streak(days) == 5
    assert compute_current_streak(days, 9) == 2


def test_backdated_approval_restores_streak() -> None:
    """Судья зачёл pending уже после закрытия дня — серия восстанавливается
    пересчётом, а не инкрементом."""
    before = compute_current_streak([1, 2, 3, 5, 6], 6)
    assert before == 2
    after = compute_current_streak([1, 2, 3, 4, 5, 6], 6)
    assert after == 6


def test_compute_streaks_returns_pair() -> None:
    assert compute_streaks([1, 2, 3], 3) == (3, 3)


def test_missed_days_ignores_future_and_prejoin() -> None:
    assert missed_days([3, 4], join_day=3, last_closed_day=6) == [5, 6]
    assert missed_days([3, 4], join_day=3, last_closed_day=2) == []


def test_completion_includes_current_day() -> None:
    completion = compute_completion(approved_count=11, join_day=1, current_day=12)
    assert (completion.approved, completion.total, completion.percent) == (11, 12, 92)


def test_completion_for_late_joiner() -> None:
    completion = compute_completion(approved_count=3, join_day=10, current_day=12)
    assert completion.total == 3
    assert completion.percent == 100


def test_calendar_string() -> None:
    assert calendar_string([1, 2, 4], [], join_day=1, current_day=5) == "✅✅❌✅⬜"


def test_calendar_marks_pending() -> None:
    assert calendar_string([1], [2], join_day=1, current_day=3) == "✅⏳⬜"


def test_calendar_starts_from_join_day() -> None:
    assert calendar_string([5, 6], [], join_day=5, current_day=7) == "✅✅⬜"
