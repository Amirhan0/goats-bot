"""Граница дня 04:00 — самое дорогое место в календаре челленджа."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from bot.services.challenge_day import (
    current_day_number,
    date_for_day,
    day_number,
    day_window,
    is_challenge_running,
    local_day_for,
    seconds_to_day_end,
)

TZ = ZoneInfo("Asia/Almaty")
START = date(2026, 9, 1)
SHIFTED = 4  # ненулевая граница: проверяем, что сдвиг всё ещё работает


def almaty(y: int, m: int, d: int, hh: int, mm: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=TZ)


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (almaty(2026, 9, 2, 0, 0), date(2026, 9, 1)),  # полночь — ещё вчерашний день
        (almaty(2026, 9, 2, 1, 30), date(2026, 9, 1)),  # пример из ТЗ
        (almaty(2026, 9, 2, 3, 59), date(2026, 9, 1)),  # последняя минута дня
        (almaty(2026, 9, 2, 4, 0), date(2026, 9, 2)),  # ровно граница — новый день
        (almaty(2026, 9, 2, 4, 1), date(2026, 9, 2)),
        (almaty(2026, 9, 2, 23, 59), date(2026, 9, 2)),
    ],
)
def test_local_day_for_boundary(moment: datetime, expected: date) -> None:
    assert local_day_for(moment, TZ, SHIFTED) == expected


def test_midnight_boundary_is_plain_calendar_day() -> None:
    """Боевая настройка: DAY_BOUNDARY_HOUR=0, ночной форы нет."""
    assert local_day_for(almaty(2026, 9, 2, 23, 59), TZ) == date(2026, 9, 2)
    assert local_day_for(almaty(2026, 9, 3, 0, 0), TZ) == date(2026, 9, 3)
    # То, что при сдвиге закрывало вчера, теперь идёт в новый день.
    assert local_day_for(almaty(2026, 9, 3, 1, 30), TZ) == date(2026, 9, 3)


def test_midnight_day_window() -> None:
    start, end = day_window(date(2026, 9, 1), TZ)
    assert start == almaty(2026, 9, 1, 0).astimezone(UTC)
    assert end == almaty(2026, 9, 2, 0).astimezone(UTC)
    assert seconds_to_day_end(almaty(2026, 9, 1, 23, 45), TZ) == 15 * 60


def test_local_day_for_requires_aware_datetime() -> None:
    with pytest.raises(ValueError, match="aware"):
        local_day_for(datetime(2026, 9, 2, 12, 0), TZ)


def test_utc_input_is_converted() -> None:
    # 2026-09-02 22:30 UTC = 2026-09-03 03:30 в Алматы → это ещё день 2 сентября
    assert local_day_for(datetime(2026, 9, 2, 22, 30, tzinfo=UTC), TZ, SHIFTED) == date(2026, 9, 2)


def test_day_window_is_half_open() -> None:
    start, end = day_window(date(2026, 9, 1), TZ, SHIFTED)
    assert start == almaty(2026, 9, 1, 4).astimezone(UTC)
    assert end == almaty(2026, 9, 2, 4).astimezone(UTC)
    assert local_day_for(start, TZ, SHIFTED) == date(2026, 9, 1)
    assert local_day_for(end, TZ, SHIFTED) == date(2026, 9, 2)


def test_day_numbering() -> None:
    assert day_number(date(2026, 9, 1), START) == 1
    assert day_number(date(2026, 9, 12), START) == 12
    assert day_number(date(2026, 8, 31), START) == 0  # до старта
    assert date_for_day(12, START) == date(2026, 9, 12)


def test_current_day_number_uses_boundary() -> None:
    assert current_day_number(almaty(2026, 9, 12, 2, 0), START, TZ, SHIFTED) == 11
    assert current_day_number(almaty(2026, 9, 12, 5, 0), START, TZ, SHIFTED) == 12


def test_seconds_to_day_end() -> None:
    assert seconds_to_day_end(almaty(2026, 9, 2, 3, 45), TZ, SHIFTED) == 15 * 60
    assert seconds_to_day_end(almaty(2026, 9, 1, 4, 0), TZ, SHIFTED) == 24 * 3600


def test_is_challenge_running() -> None:
    assert not is_challenge_running(almaty(2026, 9, 1, 3, 0), START, None, TZ, SHIFTED)
    assert is_challenge_running(almaty(2026, 9, 1, 4, 0), START, None, TZ, SHIFTED)
    assert is_challenge_running(almaty(2027, 1, 1, 12, 0), START, None, TZ, SHIFTED)
    assert not is_challenge_running(
        almaty(2026, 9, 11, 12, 0), START, date(2026, 9, 10), TZ, SHIFTED
    )
