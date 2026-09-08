from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.enums import AuditAction
from bot.db.models import AuditLog


async def log(
    session: AsyncSession,
    *,
    actor_id: int | None,
    action: AuditAction | str,
    target_type: str | None = None,
    target_id: int | None = None,
    payload: dict[str, Any] | None = None,
) -> AuditLog:
    entry = AuditLog(
        actor_id=actor_id,
        action=str(action),
        target_type=target_type,
        target_id=target_id,
        payload=payload or {},
    )
    session.add(entry)
    await session.flush()
    return entry


async def recent(session: AsyncSession, limit: int = 50) -> list[AuditLog]:
    return list(
        await session.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit))
    )
