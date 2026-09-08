"""Здоровье очереди: карточки, не доехавшие до судей."""

from __future__ import annotations

from bot.repositories import submissions as submissions_repo
from bot.services import submissions as submissions_service
from tests.conftest import make_participant, make_submission


async def test_submission_without_card_is_found(session, challenge):
    participation = await make_participant(session, challenge, 900)
    await make_submission(session, participation, 1)

    orphans = await submissions_repo.list_pending_without_card(session, challenge.id)

    assert [s.judge_message_id for s in orphans] == [None]


async def test_resend_gives_the_submission_a_card(session, bot, settings, challenge):
    participation = await make_participant(session, challenge, 901)
    submission = await make_submission(session, participation, 1)

    sent = await submissions_service.resend_missing_cards(
        session, bot, settings, challenge.id
    )

    assert sent == 1
    restored = await submissions_repo.get(session, submission.id)
    assert restored.judge_message_id is not None
    # Повторный прогон уже ничего не досылает.
    assert await submissions_service.resend_missing_cards(
        session, bot, settings, challenge.id
    ) == 0
