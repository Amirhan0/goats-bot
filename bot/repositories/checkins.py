from __future__ import annotations

from datetime import datetime
from typing import NamedTuple

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from bot.db.enums import CheckinStatus
from bot.db.models import Training, TrainingCheckin, User, display_name_of

_LOADED = (
    joinedload(TrainingCheckin.user),
    joinedload(TrainingCheckin.training),
    joinedload(TrainingCheckin.judge),
)


async def get(session: AsyncSession, checkin_id: int) -> TrainingCheckin | None:
    return await session.scalar(
        select(TrainingCheckin).where(TrainingCheckin.id == checkin_id).options(*_LOADED)
    )


async def get_for(
    session: AsyncSession, training_id: int, user_id: int
) -> TrainingCheckin | None:
    return await session.scalar(
        select(TrainingCheckin)
        .where(
            TrainingCheckin.training_id == training_id,
            TrainingCheckin.user_id == user_id,
        )
        .options(*_LOADED)
    )


async def create(
    session: AsyncSession,
    *,
    training_id: int,
    user_id: int,
    chat_id: int,
    message_id: int,
    file_id: str,
    file_unique_id: str,
    thread_id: int | None = None,
) -> TrainingCheckin:
    checkin = TrainingCheckin(
        training_id=training_id,
        user_id=user_id,
        chat_id=chat_id,
        thread_id=thread_id,
        message_id=message_id,
        file_id=file_id,
        file_unique_id=file_unique_id,
        # Приход засчитывается сразу, как и кружок: судья потом отменяет.
        status=CheckinStatus.APPROVED,
    )
    session.add(checkin)
    await session.flush()
    return checkin


async def replace_photo(
    session: AsyncSession,
    checkin: TrainingCheckin,
    *,
    message_id: int,
    file_id: str,
    file_unique_id: str,
    thread_id: int | None = None,
) -> TrainingCheckin:
    """Прислал новый скриншот вместо отклонённого — обновляем ту же запись,
    иначе уникальный индекс «один приход на тренировку» не даст создать вторую."""
    checkin.message_id = message_id
    checkin.thread_id = thread_id
    checkin.file_id = file_id
    checkin.file_unique_id = file_unique_id
    checkin.status = CheckinStatus.APPROVED
    checkin.judge_id = None
    checkin.judged_at = None
    checkin.reject_reason = None
    checkin.judge_message_id = None
    await session.flush()
    return checkin


async def set_judge_message(
    session: AsyncSession, checkin_id: int, judge_message_id: int
) -> None:
    await session.execute(
        update(TrainingCheckin)
        .where(TrainingCheckin.id == checkin_id)
        .values(judge_message_id=judge_message_id)
    )


async def claim_verdict(
    session: AsyncSession,
    checkin_id: int,
    *,
    status: CheckinStatus,
    judge_user_id: int,
    judged_at: datetime,
    reject_reason: str | None = None,
) -> bool:
    """Атомарный переход approved → rejected: судей несколько, выигрывает
    тот, чей UPDATE изменил строку.

    Стартовый статус здесь APPROVED, а не PENDING: приход засчитывается сразу,
    и единственное решение судьи — снять зачёт. Повторное нажатие по уже
    отменённому приходу строку не тронет, и второй судья увидит «уже решено».
    """
    result = await session.execute(
        update(TrainingCheckin)
        .where(
            TrainingCheckin.id == checkin_id,
            TrainingCheckin.status == CheckinStatus.APPROVED,
        )
        .values(
            status=status,
            judge_id=judge_user_id,
            judged_at=judged_at,
            reject_reason=reject_reason,
        )
        .execution_options(synchronize_session=False)
    )
    return bool(result.rowcount)


async def remember_bot_message(
    session: AsyncSession, checkin: TrainingCheckin, message_id: int | None
) -> None:
    """Список, а не одно поле: на приход бот пишет и «принято», и вердикт."""
    if not message_id:
        return
    checkin.bot_message_ids = [*(checkin.bot_message_ids or []), message_id]
    await session.flush()


async def due_cleanup(
    session: AsyncSession, older_than: datetime, limit: int = 50
) -> list[TrainingCheckin]:
    """Убирать можно только просуженные: у непроверенного скриншот —
    единственное доказательство, удалять его нельзя."""
    return list(
        await session.scalars(
            select(TrainingCheckin)
            .join(Training, TrainingCheckin.training_id == Training.id)
            .where(
                TrainingCheckin.cleaned_at.is_(None),
                TrainingCheckin.status != CheckinStatus.PENDING,
                Training.start_at < older_than,
            )
            .options(*_LOADED)
            .limit(limit)
        )
    )


async def mark_cleaned(
    session: AsyncSession, checkin: TrainingCheckin, at: datetime
) -> None:
    checkin.cleaned_at = at
    await session.flush()


async def recent(
    session: AsyncSession, since: datetime, limit: int = 20
) -> list[TrainingCheckin]:
    """Последние засчитанные приходы — для выборочной проверки судьями.

    Очереди на проверку больше нет: приход засчитывается сразу, и это
    список «на что посмотреть», а не список долгов.
    """
    return list(
        await session.scalars(
            select(TrainingCheckin)
            .where(
                TrainingCheckin.status == CheckinStatus.APPROVED,
                TrainingCheckin.created_at >= since,
            )
            .options(*_LOADED)
            .order_by(TrainingCheckin.created_at.desc())
            .limit(limit)
        )
    )


async def approved_for_training(
    session: AsyncSession, training_id: int
) -> list[TrainingCheckin]:
    return list(
        await session.scalars(
            select(TrainingCheckin)
            .where(
                TrainingCheckin.training_id == training_id,
                TrainingCheckin.status == CheckinStatus.APPROVED,
            )
            .options(*_LOADED)
            .order_by(TrainingCheckin.judged_at)
        )
    )


async def list_for_training(
    session: AsyncSession, training_id: int
) -> list[TrainingCheckin]:
    """Все приходы независимо от статуса — нужно при удалении тренировки,
    чтобы убрать из ветки и уже просуженные скриншоты, и висящие в очереди."""
    return list(
        await session.scalars(
            select(TrainingCheckin)
            .where(TrainingCheckin.training_id == training_id)
            .options(*_LOADED)
            .order_by(TrainingCheckin.id)
        )
    )


class AttendanceRow(NamedTuple):
    telegram_id: int
    name: str
    username: str | None
    visits: int


async def leaderboard(
    session: AsyncSession, since: datetime | None = None, limit: int = 20
) -> list[AttendanceRow]:
    """Рейтинг приходов. since — момент, с которого считаем: для месячного
    зачёта это полночь первого числа. Именно datetime, а не date: start_at
    хранится как момент времени."""
    visits = func.count(TrainingCheckin.id)
    stmt = (
        select(User.telegram_id, User.first_name, User.username, visits.label("visits"))
        .select_from(TrainingCheckin)
        .join(User, TrainingCheckin.user_id == User.id)
        .join(Training, TrainingCheckin.training_id == Training.id)
        .where(TrainingCheckin.status == CheckinStatus.APPROVED)
        .group_by(User.id)
        .order_by(visits.desc(), User.first_name)
        .limit(limit)
    )
    if since is not None:
        stmt = stmt.where(Training.start_at >= since)

    rows = await session.execute(stmt)
    return [
        AttendanceRow(
            telegram_id=tg,
            name=display_name_of(first_name, username, tg),
            username=username,
            visits=count,
        )
        for tg, first_name, username, count in rows
    ]


async def count_for_user(
    session: AsyncSession, user_id: int, since: datetime | None = None
) -> int:
    stmt = (
        select(func.count(TrainingCheckin.id))
        .join(Training, TrainingCheckin.training_id == Training.id)
        .where(
            TrainingCheckin.user_id == user_id,
            TrainingCheckin.status == CheckinStatus.APPROVED,
        )
    )
    if since is not None:
        stmt = stmt.where(Training.start_at >= since)
    return int(await session.scalar(stmt) or 0)
