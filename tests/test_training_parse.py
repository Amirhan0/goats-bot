"""Разбор тренировки из обычного текста."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from bot.services.training_parse import parse

TZ = ZoneInfo("Asia/Almaty")
# Четверг, 27 августа 2026, 14:00 по Алматы
NOW = datetime(2026, 8, 27, 14, 0, tzinfo=TZ)


def p(text: str):
    return parse(text, TZ, NOW)


def test_example_from_spec() -> None:
    r = p("Завтра в 19:30, Центральный стадион, интервальная тренировка 6×400")

    assert r.start_at == datetime(2026, 8, 28, 19, 30, tzinfo=TZ)
    assert r.location == "Центральный стадион"
    assert r.training_type == "Интервальная тренировка"
    assert r.description == "6×400"
    assert r.missing == ()


def test_explicit_date_with_month_name() -> None:
    r = p("28 августа в 19:30, Стадион, темповая 5 км")

    assert r.start_at == datetime(2026, 8, 28, 19, 30, tzinfo=TZ)
    assert r.training_type == "Темповая"


def test_numeric_date() -> None:
    assert p("30.08 в 08:00, Парк, кросс").start_at == datetime(2026, 8, 30, 8, 0, tzinfo=TZ)


def test_weekday_looks_forward() -> None:
    """Сегодня четверг — «во вторник» это следующая неделя."""
    r = p("во вторник в 19:00, Стадион, интервалы")
    assert r.start_at == datetime(2026, 9, 1, 19, 0, tzinfo=TZ)


def test_same_weekday_means_next_week() -> None:
    assert p("в четверг в 19:00, Стадион").start_at == datetime(2026, 9, 3, 19, 0, tzinfo=TZ)


def test_time_without_minutes() -> None:
    assert p("завтра в 19, Стадион").start_at == datetime(2026, 8, 28, 19, 0, tzinfo=TZ)


def test_time_only_picks_nearest_future() -> None:
    """19:00 сегодня ещё впереди, а 09:00 уже прошло."""
    assert p("в 19:00, Стадион").start_at == datetime(2026, 8, 27, 19, 0, tzinfo=TZ)
    assert p("в 09:00, Стадион").start_at == datetime(2026, 8, 28, 9, 0, tzinfo=TZ)


def test_date_and_time_in_separate_chunks() -> None:
    r = p("28 августа, в 19:30, Центральный стадион, забег")
    assert r.start_at == datetime(2026, 8, 28, 19, 30, tzinfo=TZ)
    assert r.location == "Центральный стадион"


def test_missing_fields_are_reported() -> None:
    assert "дата и время" in p("просто текст").missing
    assert "место" in p("завтра в 19:30").missing


def test_unknown_type_kept_as_is() -> None:
    r = p("завтра в 19:30, Парк, бежим вокруг озера")
    assert r.training_type == "бежим вокруг озера"
    assert r.description == ""


def test_invalid_date_does_not_crash() -> None:
    assert p("32.13 в 19:00, Стадион").start_at is not None  # дата отброшена, время осталось


def test_date_alone_is_parsed() -> None:
    """Шаг мастера «Дата?» приходит без времени — это не повод отказать."""
    for text in ("29.08", "29 августа", "завтра", "во вторник"):
        assert p(text).day is not None, text


def test_time_alone_is_parsed() -> None:
    for text in ("19:30", "19.30", "в 19"):
        assert p(text).clock is not None, text


def test_day_and_clock_match_start_at() -> None:
    r = p("завтра в 19:30, Стадион")
    assert r.day == r.start_at.date()
    assert r.clock == r.start_at.time()
