"""Список судей: источник истины — JUDGE_IDS, а не то, кто есть в БД."""

from __future__ import annotations

from bot import texts
from bot.repositories import users as users_repo
from tests.conftest import make_judge


async def test_map_by_telegram_ids_returns_only_known(session, settings):
    await make_judge(session, 901)

    found = await users_repo.map_by_telegram_ids(session, settings.judge_ids)

    # 901 писал боту, 902 и админ 900 — ещё нет.
    assert set(found) == {901}
    assert found[901].display_name == "Judge901"


async def test_map_by_telegram_ids_empty_input(session):
    assert await users_repo.map_by_telegram_ids(session, ()) == {}


def test_admins_count_as_judges(settings):
    # Админ автоматически судья, но в списке помечен отдельно.
    assert settings.admin_ids == (900,)
    assert set(settings.judge_ids) == {901, 902, 900}
    assert settings.is_judge(900)


def test_judges_line_marks_admin_and_unknown():
    assert texts.judges_line("Иван", "ivan", is_admin=False, known=True, verdicts=7) == (
        "• Иван (@ivan) — 7 за месяц"
    )
    assert texts.judges_line("Иван", "ivan", is_admin=True, known=True) == (
        "• Иван (@ivan) · админ — 0 за месяц"
    )
    unknown = texts.judges_line("902", None, is_admin=False, known=False)
    assert "902" in unknown
    assert "ещё не запускал бота" in unknown


def test_judges_line_escapes_html():
    line = texts.judges_line("<b>x</b>", None, is_admin=False, known=True)
    assert "<b>x</b>" not in line
    assert "&lt;b&gt;x&lt;/b&gt;" in line


def test_judge_card_shows_ids_for_undo():
    """Без номера сдачи судья не может вызвать /undo, а без id участника
    не отличит тёзок и не забанит нужного."""
    card = texts.judge_card(
        submission_id=42, telegram_id=769273084, day=3, name="Амир", username="p1kato",
        duration=61, attempt=1, code_word=None, task="планка",
        streak=5, approved=4, total=5, percent=80, flags=[],
    )

    assert "#42" in card
    assert "769273084" in card
    assert "/undo 42" in card


def test_display_name_falls_back_to_username():
    """Имя «-» в топе выглядит сломанным, поэтому падаем на @username."""
    from bot.db.models import display_name_of

    assert display_name_of("-", "kaisar", 1) == "@kaisar"
    assert display_name_of("", "kaisar", 1) == "@kaisar"
    assert display_name_of("Улдана", "u", 2) == "Улдана"
    assert display_name_of("-", None, 7) == "7"  # без ника показать нечего
