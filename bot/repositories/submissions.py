from __future__ import annotations

from datetime import date, datetime
from typing import Any, NamedTuple

from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from bot.db.enums import SubmissionStatus
from bot.db.models import Challenge, Participation, Submission, User, display_name_of

_WITH_USER = (
    joinedload(Submission.participation).joinedload(Participation.user),
    joinedload(Submission.participation).joinedload(Participation.challenge),
    joinedload(Submission.judge),
)


def _for_challenge(stmt: Select[Any], challenge_id: int) -> Select[Any]:
    return stmt.join(Participation, Submission.participation_id == Participation.id).where(
        Participation.challenge_id == challenge_id
    )


# ── чтение ───────────────────────────────────────────────────────


async def file_unique_exists(session: AsyncSession, file_unique_id: str) -> bool:
    """Глобально, а не в рамках участника: один и тот же кружок не должен
    появиться дважды ни у кого, включая уже отклонённые попытки."""
    return bool(
        await session.scalar(
            select(func.count()).select_from(Submission).where(
                Submission.file_unique_id == file_unique_id
            )
        )
    )


async def get(session: AsyncSession, submission_id: int) -> Submission | None:
    return await session.scalar(
        select(Submission).where(Submission.id == submission_id).options(*_WITH_USER)
    )


async def get_by_judge_message(
    session: AsyncSession, judge_message_id: int
) -> Submission | None:
    return await session.scalar(
        select(Submission)
        .where(Submission.judge_message_id == judge_message_id)
        .options(*_WITH_USER)
    )



async def get_approved_for_day(
    session: AsyncSession, participation_id: int, challenge_day: int
) -> Submission | None:
    return await session.scalar(
        select(Submission).where(
            Submission.participation_id == participation_id,
            Submission.challenge_day == challenge_day,
            Submission.status == SubmissionStatus.APPROVED,
        )
    )


async def last_attempt(
    session: AsyncSession, participation_id: int, challenge_day: int
) -> Submission | None:
    return await session.scalar(
        select(Submission)
        .where(
            Submission.participation_id == participation_id,
            Submission.challenge_day == challenge_day,
        )
        .order_by(Submission.attempt_no.desc())
        .limit(1)
    )


async def next_attempt_no(
    session: AsyncSession, participation_id: int, challenge_day: int
) -> int:
    current = await session.scalar(
        select(func.max(Submission.attempt_no)).where(
            Submission.participation_id == participation_id,
            Submission.challenge_day == challenge_day,
        )
    )
    return (current or 0) + 1


async def approved_days(session: AsyncSession, participation_id: int) -> set[int]:
    """Дни, закрытые участником. REVOKED тоже считается: зачёт, отменённый
    уже после закрытия дня, бьёт по месячному счёту, но серию не рвёт."""
    rows = await session.scalars(
        select(Submission.challenge_day).where(
            Submission.participation_id == participation_id,
            Submission.status.in_(SubmissionStatus.crediting_day()),
        )
    )
    return set(rows)



async def count_approved(
    session: AsyncSession, participation_id: int, since: date | None = None
) -> int:
    stmt = select(func.count(Submission.id)).where(
        Submission.participation_id == participation_id,
        Submission.status == SubmissionStatus.APPROVED,
    )
    if since is not None:
        stmt = stmt.where(Submission.day_date >= since)
    return int(await session.scalar(stmt) or 0)


async def verdicts_by_judge(
    session: AsyncSession, challenge_id: int, since: date | None = None
) -> dict[int, int]:
    """user.id судьи → сколько вердиктов вынес. Видно, кто разгребает очередь."""
    stmt = _for_challenge(
        select(Submission.judge_id, func.count(Submission.id)), challenge_id
    ).where(Submission.judge_id.is_not(None))
    if since is not None:
        stmt = stmt.where(Submission.day_date >= since)
    rows = await session.execute(stmt.group_by(Submission.judge_id))
    return {judge_id: count for judge_id, count in rows}


async def count_by_status(session: AsyncSession, participation_id: int) -> dict[str, int]:
    rows = await session.execute(
        select(Submission.status, func.count())
        .where(Submission.participation_id == participation_id)
        .group_by(Submission.status)
    )
    return {str(status.value if hasattr(status, "value") else status): n for status, n in rows}




async def list_approved_on(
    session: AsyncSession, challenge_id: int, day_date: date, limit: int | None = None
) -> list[Submission]:
    """Зачтённые кружки за день — судьям для выборочной проверки.

    Очереди «непросмотренного» больше нет: подтверждать нечего, кружок уже
    в зачёте. Судья открывает список за сегодня и смотрит, что захочет.
    """
    stmt = _for_challenge(select(Submission), challenge_id).where(
        Submission.day_date == day_date,
        Submission.status == SubmissionStatus.APPROVED,
    )
    stmt = stmt.options(*_WITH_USER).order_by(Submission.sent_at.desc())
    if limit:
        stmt = stmt.limit(limit)
    return list(await session.scalars(stmt))


async def count_approved_on(session: AsyncSession, challenge_id: int, day_date: date) -> int:
    stmt = _for_challenge(select(func.count(Submission.id)), challenge_id).where(
        Submission.day_date == day_date,
        Submission.status == SubmissionStatus.APPROVED,
    )
    return int(await session.scalar(stmt) or 0)


async def list_pending_without_card(
    session: AsyncSession, challenge_id: int
) -> list[Submission]:
    """Сдачи, для которых карточка судьям так и не ушла (сеть моргнула).
    Кнопки живут только на карточке, поэтому без неё сдачу невозможно
    засудить — а значит участник заблокирован до конца дня."""
    stmt = _for_challenge(select(Submission), challenge_id).where(
        Submission.reviewed_at.is_(None),
        Submission.status == SubmissionStatus.APPROVED,
        Submission.judge_message_id.is_(None),
    )
    return list(await session.scalars(stmt.options(*_WITH_USER).order_by(Submission.sent_at)))



async def list_for_day(
    session: AsyncSession, challenge_id: int, challenge_day: int
) -> list[Submission]:
    stmt = _for_challenge(select(Submission), challenge_id).where(
        Submission.challenge_day == challenge_day
    )
    return list(await session.scalars(stmt.options(*_WITH_USER).order_by(Submission.sent_at)))


async def count_for_day(
    session: AsyncSession, challenge_id: int, challenge_day: int, status: SubmissionStatus | None
) -> int:
    stmt = _for_challenge(select(func.count(Submission.id)), challenge_id).where(
        Submission.challenge_day == challenge_day
    )
    if status is not None:
        stmt = stmt.where(Submission.status == status)
    return int(await session.scalar(stmt) or 0)


class LeaderboardRow(NamedTuple):
    participation_id: int
    telegram_id: int
    display_name: str
    username: str | None
    approved: int
    current_streak: int
    best_streak: int


async def leaderboard(
    session: AsyncSession,
    challenge_id: int,
    since: date | None = None,
    until: date | None = None,
) -> list[LeaderboardRow]:
    """Считаются зачтённые КРУЖКИ, а не дни: сверх обязательного минимума
    можно сдавать сколько угодно, и всё идёт в зачёт.

    since/until режут период: для месячного топа since — первое число,
    для топа за день оба края совпадают.
    """
    criteria = [Submission.status == SubmissionStatus.APPROVED]
    if since is not None:
        criteria.append(Submission.day_date >= since)
    if until is not None:
        criteria.append(Submission.day_date <= until)
    approved_count = func.count(Submission.id).filter(*criteria)
    rows = await session.execute(
        select(
            Participation.id,
            User.telegram_id,
            User.first_name,
            User.username,
            approved_count.label("approved"),
            Participation.current_streak,
            Participation.best_streak,
        )
        .select_from(Participation)
        .join(User, Participation.user_id == User.id)
        .outerjoin(Submission, Submission.participation_id == Participation.id)
        .where(Participation.challenge_id == challenge_id)
        .group_by(Participation.id)
        .order_by(
            approved_count.desc(),
            Participation.current_streak.desc(),
            Participation.joined_at.asc(),
        )
    )
    return [
        LeaderboardRow(
            participation_id=pid,
            telegram_id=tg,
            display_name=display_name_of(first_name, username, tg),
            username=username,
            approved=approved,
            current_streak=cur,
            best_streak=best,
        )
        for pid, tg, first_name, username, approved, cur, best in rows
    ]


async def export_rows(session: AsyncSession, challenge_id: int) -> list[tuple[Any, ...]]:
    rows = await session.execute(
        select(
            Submission.id,
            User.telegram_id,
            User.username,
            User.first_name,
            Submission.challenge_day,
            Submission.day_date,
            Submission.attempt_no,
            Submission.duration,
            Submission.sent_at,
            Submission.status,
            Submission.reject_reason,
            Submission.judged_at,
            Submission.anti_cheat_flags,
            Submission.file_unique_id,
            Submission.verdict_message_id,
            Submission.judge_id,
        )
        .select_from(Submission)
        .join(Participation, Submission.participation_id == Participation.id)
        .join(User, Participation.user_id == User.id)
        .where(Participation.challenge_id == challenge_id)
        .order_by(Submission.id)
    )
    return [tuple(r) for r in rows]


async def dropoff_by_day(session: AsyncSession, challenge_id: int) -> list[tuple[int, int]]:
    """(день, сколько человек сдало зачтённый кружок) — видно, где сыплется."""
    rows = await session.execute(
        _for_challenge(
            select(Submission.challenge_day, func.count(func.distinct(Submission.participation_id))),
            challenge_id,
        )
        .where(Submission.status == SubmissionStatus.APPROVED)
        .group_by(Submission.challenge_day)
        .order_by(Submission.challenge_day)
    )
    return [(day, n) for day, n in rows]


# ── запись ───────────────────────────────────────────────────────


async def create(
    session: AsyncSession,
    *,
    participation_id: int,
    challenge_day: int,
    day_date: date,
    chat_id: int,
    message_id: int,
    file_id: str,
    file_unique_id: str,
    duration: int,
    sent_at: datetime,
    attempt_no: int,
    flags: list[str],
) -> Submission:
    submission = Submission(
        participation_id=participation_id,
        challenge_day=challenge_day,
        day_date=day_date,
        chat_id=chat_id,
        message_id=message_id,
        file_id=file_id,
        file_unique_id=file_unique_id,
        duration=duration,
        sent_at=sent_at,
        # Зачитываем сразу: день закрывается, серия растёт, участник не ждёт
        # судью. Судья потом либо подтверждает, либо отменяет.
        status=SubmissionStatus.APPROVED,
        anti_cheat_flags=flags,
        attempt_no=attempt_no,
    )
    session.add(submission)
    await session.flush()
    return submission


async def set_judge_messages(
    session: AsyncSession, submission_id: int, card_message_id: int, video_message_id: int
) -> None:
    await session.execute(
        update(Submission)
        .where(Submission.id == submission_id)
        .values(judge_message_id=card_message_id, judge_video_message_id=video_message_id)
    )


async def set_verdict_message(
    session: AsyncSession, submission_id: int, verdict_message_id: int | None
) -> None:
    await session.execute(
        update(Submission)
        .where(Submission.id == submission_id)
        .values(verdict_message_id=verdict_message_id)
    )


async def claim_review(
    session: AsyncSession,
    submission_id: int,
    *,
    status: SubmissionStatus,
    judge_user_id: int,
    judge_telegram_id: int,
    at: datetime,
    reject_reason: str | None = None,
) -> bool:
    """Атомарная отметка «судья посмотрел»: подтвердил или отменил зачёт.

    Судей несколько: выигрывает тот, чей UPDATE изменил строку. Второй
    получает rowcount == 0 и не трогает БД. Коммит — на вызывающей стороне.
    """
    result = await session.execute(
        update(Submission)
        .where(
            Submission.id == submission_id,
            Submission.reviewed_at.is_(None),
        )
        .values(
            status=status,
            judge_id=judge_user_id,
            judged_at=at,
            reviewed_at=at,
            reviewed_by=judge_telegram_id,
            reject_reason=reject_reason,
        )
        .execution_options(synchronize_session=False)
    )
    return bool(result.rowcount)


async def claim_undo(
    session: AsyncSession, submission_id: int, *, undone_by: int, undone_at: datetime
) -> bool:
    """Откат решения судьи: кружок снова зачтён и снова ждёт просмотра.
    Атомарный — откатить можно только то, что уже просмотрено."""
    result = await session.execute(
        update(Submission)
        .where(
            Submission.id == submission_id,
            Submission.reviewed_at.is_not(None),
        )
        .values(
            status=SubmissionStatus.APPROVED,
            judge_id=None,
            judged_at=None,
            reviewed_at=None,
            reviewed_by=None,
            reject_reason=None,
            verdict_message_id=None,
            undone_at=undone_at,
            undone_by=undone_by,
        )
        .execution_options(synchronize_session=False)
    )
    return bool(result.rowcount)


async def delete_for_test_challenges(session: AsyncSession) -> int:
    test_participations = (
        select(Participation.id)
        .join(Challenge, Participation.challenge_id == Challenge.id)
        .where(Challenge.is_test.is_(True))
    )
    deleted = await session.execute(
        delete(Submission).where(Submission.participation_id.in_(test_participations))
    )
    return int(deleted.rowcount or 0)
