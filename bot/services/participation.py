"""Вступление и выход. Календарь общий: день 1 — это всегда start_date,
независимо от того, когда человек присоединился."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Settings
from bot.db.enums import AuditAction, ParticipationStatus
from bot.db.models import Challenge, Participation, User
from bot.repositories import audit as audit_repo
from bot.repositories import participations as participations_repo
from bot.services.challenge_day import current_day_number
from bot.utils.timeutil import now_utc


@dataclass(frozen=True, slots=True)
class JoinResult:
    participation: Participation
    created: bool
    day: int


async def join(
    session: AsyncSession, settings: Settings, user: User, challenge: Challenge
) -> JoinResult:
    day = current_day_number(
        now_utc(), challenge.start_date, settings.tz, settings.day_boundary_hour
    )
    existing = await participations_repo.get(session, user.id, challenge.id)

    if existing is not None:
        if existing.status == ParticipationStatus.ACTIVE:
            return JoinResult(existing, created=False, day=day)
        # Возвращение: дни отсутствия в знаменатель не идут, серия не восстанавливается.
        existing.join_day = max(existing.join_day, max(1, day))
        await participations_repo.reactivate(session, existing)
        await audit_repo.log(
            session,
            actor_id=user.telegram_id,
            action=AuditAction.JOIN,
            target_type="participation",
            target_id=existing.id,
            payload={"day": day, "returning": True},
        )
        return JoinResult(existing, created=True, day=day)

    participation = await participations_repo.create(
        session, user_id=user.id, challenge_id=challenge.id, join_day=max(1, day)
    )
    await audit_repo.log(
        session,
        actor_id=user.telegram_id,
        action=AuditAction.JOIN,
        target_type="participation",
        target_id=participation.id,
        payload={"day": day},
    )
    return JoinResult(participation, created=True, day=day)


async def leave(
    session: AsyncSession, user: User, participation: Participation
) -> None:
    await participations_repo.leave(session, participation, now_utc())
    await audit_repo.log(
        session,
        actor_id=user.telegram_id,
        action=AuditAction.LEAVE,
        target_type="participation",
        target_id=participation.id,
    )
