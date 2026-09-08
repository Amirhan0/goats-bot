from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from bot.services.anti_cheat import (
    FlagCode,
    RejectCode,
    SubmissionContext,
    VideoNoteMeta,
    check_submission,
    collect_flags,
)

NOW = datetime(2026, 9, 12, 15, 0, tzinfo=UTC)


def meta(**kwargs) -> VideoNoteMeta:
    base = {
        "duration": 60,
        "file_unique_id": "abc",
        "is_forwarded": False,
        "via_bot": False,
        "sent_at": NOW,
    }
    return VideoNoteMeta(**{**base, **kwargs})


def ctx(**kwargs) -> SubmissionContext:
    base = {
        "is_registered": True,
        "participation_active": True,
        "user_blocked": False,
        "challenge_active": True,
        "challenge_started": True,
        "challenge_finished": False,
        "min_duration": 58,
        "max_duration": 600,
        "duplicate_exists": False,
        "current_day": 12,
        "seconds_to_deadline": 6 * 3600,
        "attempt_no": 1,
        "seconds_since_prev_attempt": None,
        "last_minutes_flag": 15,
    }
    return SubmissionContext(**{**base, **kwargs})


def test_happy_path() -> None:
    result = check_submission(meta(), ctx())
    assert result.ok
    assert result.reject is None
    assert result.flags == ()


@pytest.mark.parametrize("duration", [0, 30, 57])
def test_duration_outside_window_rejected(duration: int) -> None:
    assert check_submission(meta(duration=duration), ctx()).reject == RejectCode.BAD_DURATION


@pytest.mark.parametrize("duration", [58, 59, 60, 61, 62, 90])
def test_duration_inside_window_accepted(duration: int) -> None:
    """61 — не опечатка: Telegram округляет минутный кружок вверх."""
    assert check_submission(meta(duration=duration), ctx()).ok


def test_forwarded_rejected() -> None:
    assert check_submission(meta(is_forwarded=True), ctx()).reject == RejectCode.FORWARDED


def test_duplicate_rejected() -> None:
    assert check_submission(meta(), ctx(duplicate_exists=True)).reject == RejectCode.DUPLICATE


def test_unreviewed_submission_does_not_block() -> None:
    """Кружок зачитывается сразу — ждать судью не нужно, блокировки нет."""
    assert check_submission(meta(), ctx(attempt_no=2)).ok


def test_extra_circle_after_todays_approval_is_allowed() -> None:
    """Минимум — один кружок в день, но сверх минимума можно сколько угодно:
    именно они и определяют победителя месяца."""
    assert check_submission(meta(), ctx(attempt_no=2)).ok


def test_not_registered() -> None:
    assert (
        check_submission(meta(), ctx(is_registered=False)).reject == RejectCode.NOT_REGISTERED
    )


def test_dropped_participation() -> None:
    assert (
        check_submission(meta(), ctx(participation_active=False)).reject
        == RejectCode.LEFT_CHALLENGE
    )


def test_blocked_user_wins_over_everything() -> None:
    result = check_submission(
        meta(duration=1, is_forwarded=True), ctx(user_blocked=True, duplicate_exists=True)
    )
    assert result.reject == RejectCode.BLOCKED


def test_challenge_not_started() -> None:
    assert (
        check_submission(meta(), ctx(challenge_started=False)).reject == RejectCode.NOT_STARTED
    )


def test_challenge_finished() -> None:
    assert check_submission(meta(), ctx(challenge_finished=True)).reject == RejectCode.FINISHED


# ── флаги: не блокируют, а подсвечиваются судье ──────────────────


def test_last_minutes_flag() -> None:
    result = check_submission(meta(), ctx(seconds_to_deadline=8 * 60))
    assert result.ok
    assert FlagCode.LAST_MINUTES in result.flags


def test_no_flag_when_deadline_far() -> None:
    assert FlagCode.LAST_MINUTES not in check_submission(meta(), ctx()).flags


def test_via_bot_flag() -> None:
    assert FlagCode.VIA_BOT in check_submission(meta(via_bot=True), ctx()).flags


def test_many_attempts_flag() -> None:
    assert FlagCode.MANY_ATTEMPTS not in check_submission(meta(), ctx(attempt_no=2)).flags
    assert FlagCode.MANY_ATTEMPTS in check_submission(meta(), ctx(attempt_no=3)).flags


def test_fast_retry_flag() -> None:
    assert FlagCode.FAST_RETRY in collect_flags(meta(), ctx(seconds_since_prev_attempt=42))
    assert FlagCode.FAST_RETRY not in collect_flags(meta(), ctx(seconds_since_prev_attempt=90))


def test_flags_accumulate() -> None:
    result = check_submission(
        meta(via_bot=True),
        ctx(seconds_to_deadline=60, attempt_no=4, seconds_since_prev_attempt=10),
    )
    assert result.ok
    assert set(result.flags) == {
        FlagCode.LAST_MINUTES,
        FlagCode.VIA_BOT,
        FlagCode.MANY_ATTEMPTS,
        FlagCode.FAST_RETRY,
    }


def test_context_is_immutable() -> None:
    original = ctx()
    changed = replace(original, attempt_no=5)
    assert original.attempt_no == 1
    assert changed.attempt_no == 5
