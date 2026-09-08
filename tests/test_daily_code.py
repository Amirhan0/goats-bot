from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from bot.repositories import daily_codes as codes_repo
from bot.services import daily_code as daily_code_service

WORDS = ("абрикос", "маяк", "варежка", "компас")


def test_pick_word_avoids_recent() -> None:
    picked = {daily_code_service.pick_word(WORDS, exclude={"абрикос", "маяк"}) for _ in range(50)}
    assert picked <= {"варежка", "компас"}


def test_pick_word_falls_back_when_pool_exhausted() -> None:
    assert daily_code_service.pick_word(WORDS, exclude=set(WORDS)) in WORDS


def test_load_words_skips_comments_and_duplicates(tmp_path: Path) -> None:
    path = tmp_path / "w.txt"
    path.write_text("# коммент\nмаяк\nМАЯК\n\nкомпас\n", encoding="utf-8")
    assert daily_code_service.load_words(path) == ("маяк", "компас")


def test_real_dictionary_is_large_enough() -> None:
    words = daily_code_service.load_words(Path("data/words.txt"))
    assert len(words) >= 300
    assert len(set(words)) == len(words)


async def test_ensure_code_is_stable_within_day(session, settings, challenge) -> None:
    settings_with_code = replace_settings(settings, daily_code_enabled=True)
    day = date(2026, 9, 12)

    first = await daily_code_service.ensure_code(session, challenge, day, settings_with_code)
    second = await daily_code_service.ensure_code(session, challenge, day, settings_with_code)
    assert first == second


async def test_ensure_code_avoids_repeats_in_window(session, settings, challenge) -> None:
    settings_with_code = replace_settings(settings, daily_code_enabled=True)
    start = date(2026, 9, 1)

    codes = []
    for offset in range(25):
        codes.append(
            await daily_code_service.ensure_code(
                session, challenge, start + timedelta(days=offset), settings_with_code
            )
        )
    assert len(set(codes)) == len(codes)


async def test_manual_code_overrides_generated(session, settings, challenge) -> None:
    day = date(2026, 9, 20)
    await daily_code_service.set_manual_code(session, challenge, day, "  Абрикос ")
    stored = await codes_repo.get(session, challenge.id, day)
    assert stored.code == "абрикос"
    assert stored.is_manual is True


async def test_disabled_flag_returns_none(session, settings, challenge) -> None:
    assert await daily_code_service.ensure_code(
        session, challenge, date(2026, 9, 12), settings
    ) is None


def replace_settings(settings, **kwargs):
    """Settings — pydantic-модель, копию делаем через model_copy."""
    return settings.model_copy(update=kwargs)
