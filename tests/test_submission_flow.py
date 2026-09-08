"""Сквозной путь приёма кружка: проверки → запись → карточка судьям."""

from __future__ import annotations

from datetime import UTC, datetime

from bot.db.enums import SubmissionStatus
from bot.repositories import submissions as submissions_repo
from bot.repositories import users as users_repo
from bot.services import submissions as submissions_service
from bot.services.anti_cheat import VideoNoteMeta
from tests.conftest import PARTICIPANTS_CHAT, make_participant

# 2026-09-12 15:00 по Алматы = день 12 челленджа
SENT_AT = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)


def meta(file_unique_id: str = "u1", duration: int = 60, **kwargs) -> VideoNoteMeta:
    return VideoNoteMeta(
        duration=duration,
        file_unique_id=file_unique_id,
        is_forwarded=kwargs.get("is_forwarded", False),
        via_bot=kwargs.get("via_bot", False),
        sent_at=kwargs.get("sent_at", SENT_AT),
    )


async def _accept(session, bot, settings, user, file_unique_id="u1", **kwargs):
    return await submissions_service.accept_video_note(
        session,
        bot,
        settings,
        user=user,
        chat_id=PARTICIPANTS_CHAT,
        message_id=kwargs.pop("message_id", 42),
        file_id="file-42",
        meta=meta(file_unique_id, **kwargs),
    )


async def test_accepted_submission_is_stored_and_sent_to_judges(
    session, settings, bot, challenge
):
    await make_participant(session, challenge, 700)
    user = await users_repo.get_by_telegram_id(session, 700)

    outcome = await _accept(session, bot, settings, user)

    assert outcome.accepted
    assert "День 12" in outcome.text
    assert "за сентябрь: <b>1</b> кружок" in outcome.text
    assert "<i>" in outcome.text  # высказывание

    stored = await submissions_repo.get(session, outcome.submission_id)
    assert stored.status == SubmissionStatus.APPROVED
    assert stored.challenge_day == 12
    assert stored.attempt_no == 1
    assert stored.judge_message_id is not None

    to_judges = bot.sent_to(settings.judges_chat_id)
    assert len(to_judges) == 2  # копия кружка + карточка с кнопками
    card = to_judges[1]["text"]
    assert "День 12" in card and "Кружок №1 за день" in card
    assert to_judges[1]["reply_markup"] is not None


async def test_second_attempt_after_rejection(session, settings, bot, challenge):
    await make_participant(session, challenge, 701)
    user = await users_repo.get_by_telegram_id(session, 701)

    first = await _accept(session, bot, settings, user, "a1")
    stored = await submissions_repo.get(session, first.submission_id)
    stored.status = SubmissionStatus.REJECTED
    await session.commit()

    second = await _accept(session, bot, settings, user, "a2")
    assert second.accepted

    again = await submissions_repo.get(session, second.submission_id)
    assert again.attempt_no == 2
    assert again.challenge_day == 12


async def test_next_circle_is_not_blocked_by_unreviewed(session, settings, bot, challenge):
    """Раньше второй кружок ждал вердикта по первому. Теперь оба зачтены сразу."""
    await make_participant(session, challenge, 702)
    user = await users_repo.get_by_telegram_id(session, 702)

    first = await _accept(session, bot, settings, user, "b1")
    second = await _accept(session, bot, settings, user, "b2")

    assert first.accepted and second.accepted
    stored = await submissions_repo.get(session, second.submission_id)
    assert stored.attempt_no == 2
    assert stored.reviewed_at is None


async def test_duplicate_file_is_rejected_globally(session, settings, bot, challenge):
    await make_participant(session, challenge, 703)
    await make_participant(session, challenge, 704)
    first_user = await users_repo.get_by_telegram_id(session, 703)
    second_user = await users_repo.get_by_telegram_id(session, 704)

    await _accept(session, bot, settings, first_user, "shared")
    outcome = await _accept(session, bot, settings, second_user, "shared")

    assert not outcome.accepted
    assert "уже отправляли" in outcome.text


async def test_short_video_note_rejected_without_db_record(session, settings, bot, challenge):
    participation = await make_participant(session, challenge, 705)
    user = await users_repo.get_by_telegram_id(session, 705)

    outcome = await _accept(session, bot, settings, user, "c1", duration=42)

    assert not outcome.accepted
    assert "42 сек" in outcome.text
    assert await submissions_repo.next_attempt_no(session, participation.id, 12) == 1


async def test_unregistered_user_is_rejected(session, settings, bot, challenge):
    from bot.db.models import User

    user = User(telegram_id=706, username="nobody", first_name="Nobody")
    session.add(user)
    await session.commit()

    outcome = await _accept(session, bot, settings, user)
    assert not outcome.accepted
    assert "/start" in outcome.text


async def test_last_minutes_flag_reaches_judge_card(session, settings, bot, challenge):
    await make_participant(session, challenge, 707)
    user = await users_repo.get_by_telegram_id(session, 707)

    # 2026-09-12 22:50 UTC = 03:50 по Алматы 13-го → до дедлайна 10 минут,
    # и это ещё день 12 челленджа.
    outcome = await _accept(
        session,
        bot,
        settings,
        user,
        "d1",
        sent_at=datetime(2026, 9, 12, 22, 50, tzinfo=UTC),
    )

    assert outcome.accepted
    stored = await submissions_repo.get(session, outcome.submission_id)
    assert stored.challenge_day == 12
    assert "last_minutes" in stored.anti_cheat_flags
    assert "Флаги" in bot.sent_to(settings.judges_chat_id)[1]["text"]


async def test_join_button_ignored_outside_challenge_chat(settings):
    """Бот сидит в нескольких группах клуба. Вступить можно только из беседы
    челленджа: иначе кружки оттуда не примутся, а человек будет каждую ночь
    висеть в «Пропустили»."""
    assert settings.in_participants_thread(PARTICIPANTS_CHAT, None)
    assert not settings.in_participants_thread(-1009999999999, None)
