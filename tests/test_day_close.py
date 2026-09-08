"""Закрытие дня: пропуски, обнуление серий, pending не сгорает."""

from __future__ import annotations

from datetime import date

from bot.db.enums import SubmissionStatus
from bot.repositories import participations as participations_repo
from bot.services import day_close as day_close_service
from tests.conftest import make_participant, make_submission

DAY_3 = date(2026, 9, 3)


async def _approve(session, participation, day):
    submission = await make_submission(session, participation, day)
    submission.status = SubmissionStatus.APPROVED
    await session.commit()
    return submission


async def test_missed_day_resets_streak_and_records_break(session, settings, bot, challenge):
    participation = await make_participant(session, challenge, 600)
    await _approve(session, participation, 1)
    await _approve(session, participation, 2)
    participation.current_streak = 2
    await session.commit()

    report = await day_close_service.close_day(session, settings, DAY_3)

    assert report.day == 3
    assert report.missed == ["U600"]
    assert report.streaks_broken == 1
    assert report.broken == ["U600 (2)"]

    refreshed = await participations_repo.get_by_id(session, participation.id)
    assert refreshed.current_streak == 0
    assert refreshed.best_streak == 2

    # В 04:00 личных уведомлений нет: всё сводится в пост дня в 04:05.
    assert not bot.calls


async def test_approved_day_keeps_streak(session, settings, bot, challenge):
    participation = await make_participant(session, challenge, 601)
    for day in (1, 2, 3):
        await _approve(session, participation, day)

    report = await day_close_service.close_day(session, settings, DAY_3)

    assert report.done == ["U601"]
    assert report.missed == []
    refreshed = await participations_repo.get_by_id(session, participation.id)
    assert refreshed.current_streak == 3


async def test_unreviewed_submission_closes_the_day(session, settings, bot, challenge):
    """Кружок зачтён сразу, даже если судья до него ещё не дошёл — день закрыт,
    серия жива. Раньше здесь висел pending и всё зависело от скорости судьи."""
    participation = await make_participant(session, challenge, 602)
    await _approve(session, participation, 1)
    await _approve(session, participation, 2)
    unreviewed = await make_submission(session, participation, 3)
    assert unreviewed.reviewed_at is None

    report = await day_close_service.close_day(session, settings, DAY_3)

    assert report.done == ["U602"]
    assert report.missed == []
    assert report.broken == []


async def test_backdated_approval_restores_streak(session, settings, bot, challenge):
    """Судья зачёл вчерашний pending уже после закрытия — серия должна
    восстановиться пересчётом, а не остаться обнулённой."""
    participation = await make_participant(session, challenge, 603)
    await _approve(session, participation, 1)
    await _approve(session, participation, 2)
    late = await make_submission(session, participation, 3)

    await day_close_service.close_day(session, settings, DAY_3)

    late.status = SubmissionStatus.APPROVED
    await session.commit()

    from bot.services import stats as stats_service

    current, _best = await stats_service.refresh_streaks(session, participation, 4)
    assert current == 3


async def test_late_joiner_is_not_penalised(session, settings, bot, challenge):
    await make_participant(session, challenge, 604, join_day=5)

    report = await day_close_service.close_day(session, settings, DAY_3)

    assert report.missed == []
    assert report.done == []


async def test_day_before_start_is_noop(session, settings, bot, challenge):
    await make_participant(session, challenge, 605)
    report = await day_close_service.close_day(session, settings, date(2026, 8, 30))
    assert report.day < 1
    assert report.missed == []
