"""Судей несколько — вердикт должен быть ровно один."""

from __future__ import annotations

import asyncio

from bot.db.enums import SubmissionStatus
from bot.db.models import Submission
from bot.repositories import submissions as submissions_repo
from bot.repositories import users as users_repo
from bot.services import moderation as moderation_service
from tests.conftest import make_judge, make_participant, make_submission

CARD = "День 12 · U500"


async def _verdict(sessionmaker, bot, settings, submission_id, judge_tg, approve, reason=None):
    async with sessionmaker() as s:
        judge = await users_repo.get_by_telegram_id(s, judge_tg)
        return await moderation_service.apply_verdict(
            s,
            bot,
            settings,
            submission_id=submission_id,
            judge=judge,
            approve=approve,
            reason_text=reason,
            card_text=CARD,
            edit_message=(settings.judges_chat_id, 555),
        )


async def test_two_judges_press_simultaneously(sessionmaker, session, settings, bot, challenge):
    participation = await make_participant(session, challenge, 500)
    await make_judge(session, 901)
    await make_judge(session, 902)
    submission = await make_submission(session, participation, 12)

    first, second = await asyncio.gather(
        _verdict(sessionmaker, bot, settings, submission.id, 901, True),
        _verdict(sessionmaker, bot, settings, submission.id, 902, False, "повтор"),
    )

    assert sorted([first.status, second.status]) == ["already", "ok"]

    async with sessionmaker() as s:
        stored = await submissions_repo.get(s, submission.id)
        # Кто именно выиграл гонку — не важно и недетерминировано. Важно, что
        # решение ровно одно и сдача отмечена просмотренной.
        assert stored.reviewed_at is not None
        assert stored.reviewed_by == stored.judge.telegram_id
        assert stored.judge_id is not None
        assert stored.judged_at is not None


async def test_second_judge_gets_popup_with_first_judge_name(
    sessionmaker, session, settings, bot, challenge
):
    participation = await make_participant(session, challenge, 501)
    await make_judge(session, 901)
    await make_judge(session, 902)
    submission = await make_submission(session, participation, 3)

    first = await _verdict(sessionmaker, bot, settings, submission.id, 901, True)
    assert first.status == "ok"

    second = await _verdict(sessionmaker, bot, settings, submission.id, 902, False, "повтор")
    assert second.status == "already"
    assert "judge901" in second.popup
    assert second.alert is True


async def test_same_button_pressed_twice_is_idempotent(
    sessionmaker, session, settings, bot, challenge
):
    participation = await make_participant(session, challenge, 502)
    await make_judge(session, 901)
    submission = await make_submission(session, participation, 4)

    await _verdict(sessionmaker, bot, settings, submission.id, 901, True)

    async with sessionmaker() as s:
        before = await submissions_repo.get(s, submission.id)
        judged_at, judge_id = before.judged_at, before.judge_id

    repeat = await _verdict(sessionmaker, bot, settings, submission.id, 901, True)
    assert repeat.status == "already"

    async with sessionmaker() as s:
        after = await submissions_repo.get(s, submission.id)
        assert (after.judged_at, after.judge_id) == (judged_at, judge_id)


async def test_judge_cannot_judge_own_submission(sessionmaker, session, settings, bot, challenge):
    participation = await make_participant(session, challenge, 901)  # судья-участник
    submission = await make_submission(session, participation, 5)

    result = await _verdict(sessionmaker, bot, settings, submission.id, 901, True)
    assert result.status == "self"

    async with sessionmaker() as s:
        stored = await submissions_repo.get(s, submission.id)
        assert stored.status == SubmissionStatus.APPROVED
        assert stored.reviewed_at is None


async def test_undo_returns_submission_to_queue(sessionmaker, session, settings, bot, challenge):
    participation = await make_participant(session, challenge, 503)
    await make_judge(session, 901)
    submission = await make_submission(session, participation, 6)

    await _verdict(sessionmaker, bot, settings, submission.id, 901, True)

    async with sessionmaker() as s:
        judge = await users_repo.get_by_telegram_id(s, 901)
        result = await moderation_service.undo(
            s, bot, settings, submission_id=submission.id, actor=judge
        )
    assert result.ok

    async with sessionmaker() as s:
        stored = await submissions_repo.get(s, submission.id)
        assert stored.status == SubmissionStatus.APPROVED
        assert stored.reviewed_at is None  # снова в очереди на просмотр
        assert stored.judge_id is None
        assert stored.undone_by == 901


async def test_undo_rejected_for_foreign_verdict(sessionmaker, session, settings, bot, challenge):
    participation = await make_participant(session, challenge, 504)
    await make_judge(session, 901)
    await make_judge(session, 902)
    submission = await make_submission(session, participation, 7)

    await _verdict(sessionmaker, bot, settings, submission.id, 901, True)

    async with sessionmaker() as s:
        other = await users_repo.get_by_telegram_id(s, 902)
        result = await moderation_service.undo(
            s, bot, settings, submission_id=submission.id, actor=other
        )
    assert not result.ok


async def test_several_approved_per_day_are_allowed(session, challenge):
    """Уникального индекса «один зачёт в день» больше нет: сверх обязательного
    минимума кружки копятся и идут в месячный зачёт."""
    participation = await make_participant(session, challenge, 505)
    first = await make_submission(session, participation, 8, attempt_no=1)
    first.status = SubmissionStatus.APPROVED
    await session.commit()

    second = Submission(
        participation_id=participation.id,
        challenge_day=8,
        day_date=first.day_date,
        message_id=1,
        file_id="f2",
        file_unique_id="uniq-second",
        duration=60,
        sent_at=first.sent_at,
        attempt_no=2,
        status=SubmissionStatus.APPROVED,
        anti_cheat_flags=[],
    )
    session.add(second)
    await session.commit()

    approved = await submissions_repo.count_approved(session, participation.id)
    assert approved == 2
    # А серия всё равно считается по РАЗЛИЧНЫМ дням.
    assert await submissions_repo.approved_days(session, participation.id) == {8}


def _chat_replies(bot, settings):
    return [
        kw
        for name, kw in bot.calls
        if name == "send_message" and kw.get("chat_id") == settings.participants_chat_id
    ]


async def test_confirmation_is_silent(sessionmaker, session, settings, bot, challenge):
    """Кружок уже помечен зачтённым при приёме — подтверждать это вслух незачем."""
    participation = await make_participant(session, challenge, 508)
    await make_judge(session, 901)
    submission = await make_submission(session, participation, 11)

    result = await _verdict(sessionmaker, bot, settings, submission.id, 901, True)

    assert result.status == "ok"
    assert _chat_replies(bot, settings) == []

    # Молча — но не бесследно: реакция на кружке меняется с «не смотрел» на 🏆.
    reactions = [kw for name, kw in bot.calls if name == "set_message_reaction"]
    assert reactions and reactions[-1]["reaction"][0].emoji == "🏆"

    async with sessionmaker() as s:
        stored = await submissions_repo.get(s, submission.id)
        assert stored.status == SubmissionStatus.APPROVED
        assert stored.reviewed_at is not None


async def test_revoke_is_announced_in_participants_chat(
    sessionmaker, session, settings, bot, challenge
):
    """Отмена — единственное, о чём бот говорит в беседе."""
    telegram_id = 506
    participation = await make_participant(session, challenge, telegram_id)
    await make_judge(session, 901)
    submission = await make_submission(session, participation, 9)

    await _verdict(sessionmaker, bot, settings, submission.id, 901, False, "повтор")

    replies = _chat_replies(bot, settings)
    assert len(replies) == 1
    assert replies[0]["reply_to_message_id"] == submission.message_id
    assert "отменён" in replies[0]["text"]
    assert f'tg://user?id={telegram_id}' in replies[0]["text"]
    assert "Судья: Judge901" in replies[0]["text"]

    async with sessionmaker() as s:
        stored = await submissions_repo.get(s, submission.id)
        assert stored.verdict_message_id is not None


async def test_undo_deletes_verdict_reply(sessionmaker, session, settings, bot, challenge):
    participation = await make_participant(session, challenge, 507)
    await make_judge(session, 901)
    submission = await make_submission(session, participation, 10)

    await _verdict(sessionmaker, bot, settings, submission.id, 901, False, "повтор")
    async with sessionmaker() as s:
        revoked = await submissions_repo.get(s, submission.id)
        verdict_message_id = revoked.verdict_message_id

    async with sessionmaker() as s:
        judge = await users_repo.get_by_telegram_id(s, 901)
        result = await moderation_service.undo(
            s, bot, settings, submission_id=submission.id, actor=judge
        )
    assert result.ok

    deleted = [kw for name, kw in bot.calls if name == "delete_message"]
    assert {"chat_id": settings.participants_chat_id, "message_id": verdict_message_id} in deleted

    async with sessionmaker() as s:
        stored = await submissions_repo.get(s, submission.id)
        assert stored.verdict_message_id is None
