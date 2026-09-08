"""Похвала за кружок: счётчик, круглые числа, высказывание."""

from __future__ import annotations

from pathlib import Path

from bot import texts
from bot.services import motivation


def test_quotes_file_is_loaded() -> None:
    quotes = motivation.load_quotes(Path("data/quotes.json"))

    assert len(quotes) >= 40
    assert len({q.text for q in quotes}) == len(quotes), "есть дубли цитат"
    assert any(q.author for q in quotes), "нигде нет автора"


def test_author_is_rendered_when_known() -> None:
    assert motivation.Quote("Текст", "Автор").render() == "Текст — Автор"
    assert motivation.Quote("Текст").render() == "Текст"


def test_missing_file_falls_back(tmp_path: Path) -> None:
    assert motivation.load_quotes(tmp_path / "нет.json") == motivation.FALLBACK_QUOTES


def test_broken_json_falls_back(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{не json", encoding="utf-8")
    assert motivation.load_quotes(broken) == motivation.FALLBACK_QUOTES


def test_quotes_do_not_repeat_soon() -> None:
    """Пока не пройдёт две трети пула, цитата повториться не должна."""
    path = Path("data/quotes.json")
    total = len(motivation.load_quotes(path))
    window = total * 2 // 3

    motivation._recent_quotes.clear()
    picked = [motivation.pick_quote(path) for _ in range(window)]

    assert len(set(picked)) == len(picked)


def test_milestones_only_on_round_numbers() -> None:
    assert motivation.milestone(1) is None
    assert motivation.milestone(7) is None
    assert "Десять" in motivation.milestone(10)
    assert "СОТНЯ" in motivation.milestone(100)


def test_praise_comes_from_pool() -> None:
    assert {motivation.pick_praise() for _ in range(50)} <= set(motivation.PRAISE)


def _accepted(**kwargs) -> str:
    base = dict(
        praise="красава",
        circles_month=3,
        month="сентябрь",
        streak=2,
        quote="Регулярность бьёт интенсивность.",
    )
    return texts.accepted("Амир", 5, kwargs.pop("attempt", 1), **{**base, **kwargs})


def test_message_has_count_streak_and_quote() -> None:
    text = _accepted()

    assert "Амир, красава!" in text
    assert "День 5" in text
    assert "за сентябрь: <b>3</b> кружка" in text
    assert "серия 2 дня" in text
    assert "Регулярность бьёт интенсивность." in text


def test_second_circle_of_the_day_is_marked() -> None:
    assert "Кружок №2 за сегодня" in _accepted(attempt=2)
    assert "Кружок №" not in _accepted(attempt=1)


def test_milestone_line_included_when_given() -> None:
    text = _accepted(milestone="🔟 Десять кружков. Уже не случайность.")
    assert "Десять кружков" in text
