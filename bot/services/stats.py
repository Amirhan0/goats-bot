"""Производные числа: серии, проценты, календарь, топ, дашборд.

Единственное место, где Participation.current_streak / best_streak получают
новые значения — refresh_streaks(). Всё остальное только читает.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.enums import SubmissionStatus
from bot.db.models import Participation
from bot.repositories import participations as participations_repo
from bot.repositories import submissions as submissions_repo
from bot.services import streaks as streaks_service


@dataclass(frozen=True, slots=True)
class Progress:
    current_streak: int
    best_streak: int
    approved: int
    total: int
    percent: int


@dataclass(frozen=True, slots=True)
class UserStats:
    day: int
    current_streak: int
    best_streak: int
    approved: int          # закрытых дней (для процента и серии)
    circles_total: int     # всего зачтённых кружков
    circles_month: int     # зачтённых кружков в текущем месяце
    rejected: int
    missed: int
    total: int
    percent: int
    calendar: str


async def refresh_streaks(
    session: AsyncSession, participation: Participation, current_day: int
) -> tuple[int, int]:
    """Пересчёт из истории approved-дней. Вызывается после каждого вердикта,
    отката и закрытия дня — поэтому зачёт задним числом восстанавливает серию."""
    days = await submissions_repo.approved_days(session, participation.id)
    current, best = streaks_service.compute_streaks(days, current_day)
    await participations_repo.set_streaks(session, participation, current, best)
    return current, participation.best_streak


async def get_progress(
    session: AsyncSession, participation: Participation, current_day: int
) -> Progress:
    days = await submissions_repo.approved_days(session, participation.id)
    current, best = streaks_service.compute_streaks(days, current_day)
    completion = streaks_service.compute_completion(
        len(days), participation.join_day, current_day
    )
    return Progress(
        current_streak=current,
        best_streak=max(best, participation.best_streak),
        approved=completion.approved,
        total=completion.total,
        percent=completion.percent,
    )


async def build_user_stats(
    session: AsyncSession,
    participation: Participation,
    current_day: int,
    month_since: date | None = None,
) -> UserStats:
    approved = await submissions_repo.approved_days(session, participation.id)
    counts = await submissions_repo.count_by_status(session, participation.id)

    current, best = streaks_service.compute_streaks(approved, current_day)
    completion = streaks_service.compute_completion(
        len(approved), participation.join_day, current_day
    )
    # Пропуск = закрытый день без зачёта. Сегодняшний день ещё не закрыт.
    missed = len(
        streaks_service.missed_days(approved, participation.join_day, current_day - 1)
    )

    return UserStats(
        circles_total=await submissions_repo.count_approved(session, participation.id),
        circles_month=await submissions_repo.count_approved(
            session, participation.id, month_since
        ),
        day=current_day,
        current_streak=current,
        best_streak=max(best, participation.best_streak),
        approved=completion.approved,
        rejected=counts.get(SubmissionStatus.REJECTED.value, 0),
        missed=max(0, missed),
        total=completion.total,
        percent=completion.percent,
        calendar=streaks_service.calendar_string(
            approved, (), participation.join_day, current_day
        ),
    )


@dataclass(frozen=True, slots=True)
class TopEntry:
    place: int
    name: str
    approved: int
    streak: int
    participation_id: int


async def build_top(
    session: AsyncSession,
    challenge_id: int,
    limit: int = 10,
    since: date | None = None,
) -> list[TopEntry]:
    rows = await submissions_repo.leaderboard(session, challenge_id, since)
    return [
        TopEntry(
            place=i,
            name=row.display_name,
            approved=row.approved,
            streak=row.current_streak,
            participation_id=row.participation_id,
        )
        for i, row in enumerate(rows, start=1)
    ][: limit if limit else None]


async def find_place(
    session: AsyncSession,
    challenge_id: int,
    participation_id: int,
    since: date | None = None,
) -> tuple[int, int] | None:
    rows = await submissions_repo.leaderboard(session, challenge_id, since)
    for i, row in enumerate(rows, start=1):
        if row.participation_id == participation_id:
            return i, len(rows)
    return None


@dataclass(frozen=True, slots=True)
class Dashboard:
    active: int
    submitted_today: int
    approved_today: int
    avg_percent: int
    dropoff: list[tuple[int, int]]


async def build_dashboard(
    session: AsyncSession, challenge_id: int, current_day: int
) -> Dashboard:
    active = await participations_repo.list_active(session, challenge_id)
    submitted = await submissions_repo.count_for_day(session, challenge_id, current_day, None)
    approved = await submissions_repo.count_for_day(
        session, challenge_id, current_day, SubmissionStatus.APPROVED
    )

    percents: list[int] = []
    for participation in active:
        progress = await get_progress(session, participation, current_day)
        percents.append(progress.percent)

    return Dashboard(
        active=len(active),
        submitted_today=submitted,
        approved_today=approved,
        avg_percent=round(sum(percents) / len(percents)) if percents else 0,
        dropoff=await submissions_repo.dropoff_by_day(session, challenge_id),
    )
