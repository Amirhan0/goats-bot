"""Месячный зачёт: побеждает тот, у кого больше зачтённых кружков за месяц."""

from __future__ import annotations

from datetime import UTC, date, datetime

from bot.db.enums import SubmissionStatus
from bot.db.models import Submission
from bot.repositories import submissions as submissions_repo
from bot.services import stats as stats_service
from bot.services.challenge_day import month_start
from tests.conftest import PARTICIPANTS_CHAT, make_participant

SEPT = date(2026, 9, 1)
OCT = date(2026, 10, 1)


async def _approve(session, participation, day_date: date, n: int) -> None:
    """n зачтённых кружков в один день — так и копится месячный счёт."""
    for i in range(n):
        session.add(
            Submission(
                participation_id=participation.id,
                challenge_day=(day_date - SEPT).days + 1,
                day_date=day_date,
                chat_id=PARTICIPANTS_CHAT,
                message_id=1000 + i,
                file_id=f"f-{participation.id}-{day_date}-{i}",
                file_unique_id=f"u-{participation.id}-{day_date}-{i}",
                duration=60,
                sent_at=datetime(day_date.year, day_date.month, day_date.day, 12, tzinfo=UTC),
                attempt_no=i + 1,
                status=SubmissionStatus.APPROVED,
                anti_cheat_flags=[],
            )
        )
    await session.commit()


def test_month_start() -> None:
    assert month_start(date(2026, 9, 17)) == date(2026, 9, 1)
    assert month_start(date(2026, 10, 1)) == date(2026, 10, 1)


async def test_more_circles_per_day_win_the_month(session, challenge):
    grinder = await make_participant(session, challenge, 800)
    steady = await make_participant(session, challenge, 801)

    # Один сдаёт по три кружка два дня, другой — по одному четыре дня.
    await _approve(session, grinder, date(2026, 9, 1), 3)
    await _approve(session, grinder, date(2026, 9, 2), 3)
    for offset in range(4):
        await _approve(session, steady, date(2026, 9, 1 + offset), 1)

    top = await stats_service.build_top(session, challenge.id, since=SEPT)

    assert [(e.place, e.name, e.approved) for e in top] == [
        (1, "U800", 6),
        (2, "U801", 4),
    ]


async def test_previous_month_does_not_count(session, challenge):
    participation = await make_participant(session, challenge, 802)
    await _approve(session, participation, date(2026, 9, 20), 5)
    await _approve(session, participation, date(2026, 10, 2), 2)

    september = await submissions_repo.count_approved(session, participation.id, SEPT)
    october = await submissions_repo.count_approved(session, participation.id, OCT)
    total = await submissions_repo.count_approved(session, participation.id)

    assert (september, october, total) == (7, 2, 7)


async def test_alltime_top_counts_everything(session, challenge):
    first = await make_participant(session, challenge, 803)
    second = await make_participant(session, challenge, 804)

    await _approve(session, first, date(2026, 9, 5), 4)  # набрал в сентябре
    await _approve(session, second, date(2026, 10, 5), 6)  # набрал в октябре

    october = await stats_service.build_top(session, challenge.id, since=OCT)
    alltime = await stats_service.build_top(session, challenge.id, since=None)

    assert [e.name for e in october] == ["U804", "U803"]
    assert october[1].approved == 0  # сентябрь в октябрьский зачёт не идёт
    assert {e.name: e.approved for e in alltime} == {"U804": 6, "U803": 4}


async def test_streak_counts_days_not_circles(session, challenge):
    """Три кружка за один день — это всё ещё один день серии."""
    participation = await make_participant(session, challenge, 805)
    await _approve(session, participation, date(2026, 9, 1), 3)

    stats = await stats_service.build_user_stats(session, participation, 1, SEPT)

    assert stats.circles_month == 3
    assert stats.circles_total == 3
    assert stats.approved == 1  # закрытый день ровно один
    assert stats.current_streak == 1


async def test_my_place_found_in_monthly_scope(session, challenge):
    first = await make_participant(session, challenge, 806)
    second = await make_participant(session, challenge, 807)
    await _approve(session, first, date(2026, 9, 3), 2)
    await _approve(session, second, date(2026, 9, 3), 5)

    place = await stats_service.find_place(session, challenge.id, first.id, SEPT)

    assert place == (2, 2)


async def test_day_top_counts_only_that_day(session, challenge):
    """Топ за день не смешивается с месячным: вчерашний объём не тянется."""
    grinder = await make_participant(session, challenge, 970)
    steady = await make_participant(session, challenge, 971)
    await _approve(session, grinder, SEPT, 40)            # вчера много
    await _approve(session, grinder, date(2026, 9, 2), 1)  # сегодня один
    await _approve(session, steady, date(2026, 9, 2), 5)   # сегодня пять

    day = await submissions_repo.leaderboard(
        session, challenge.id, since=date(2026, 9, 2), until=date(2026, 9, 2)
    )
    month = await submissions_repo.leaderboard(session, challenge.id, month_start(SEPT))

    assert [(r.telegram_id, r.approved) for r in day if r.approved] == [(971, 5), (970, 1)]
    # а за месяц порядок обратный — там объём решает
    assert [(r.telegram_id, r.approved) for r in month if r.approved] == [(970, 41), (971, 5)]
