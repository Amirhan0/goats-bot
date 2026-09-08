"""Какой челлендж считается текущим и как он создаётся при первом запуске."""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Settings
from bot.db.models import Challenge, Club
from bot.repositories import challenges as challenges_repo
from bot.services.challenge_day import local_day_for
from bot import texts
from bot.utils.timeutil import now_utc

logger = logging.getLogger(__name__)


async def get_current(
    session: AsyncSession, settings: Settings, club: Club | None = None
) -> Challenge | None:
    """Активный челлендж клуба.

    Флаг TEST_MODE по-прежнему разводит тестовый и боевой — они живут в базе
    параллельно. Клуб добавляет второе измерение: у каждой группы свой
    челлендж, и лидерборды у них не пересекаются.
    """
    club_id = club.id if club is not None else settings.active_club_id
    return await challenges_repo.get_active(
        session, is_test=settings.test_mode, club_id=club_id
    )


async def ensure_current(
    session: AsyncSession, settings: Settings, club: Club | None = None
) -> Challenge:
    existing = await get_current(session, settings, club)
    if existing is not None:
        return existing

    club_id = club.id if club is not None else settings.active_club_id
    start = _start_date_for(settings)
    challenge = await challenges_repo.create(
        session,
        title=settings.challenge_title + (" (тест)" if settings.test_mode else ""),
        start_date=start,
        is_test=settings.test_mode,
        min_duration_sec=settings.min_duration_sec,
        max_duration_sec=settings.max_duration_sec,
        club_id=club_id,
    )
    await challenges_repo.deactivate_others(
        session, is_test=settings.test_mode, keep_id=challenge.id, club_id=club_id
    )
    logger.info(
        "Создан челлендж #%s «%s», старт %s, is_test=%s",
        challenge.id,
        challenge.title,
        start,
        challenge.is_test,
    )
    return challenge


def _start_date_for(settings: Settings) -> date:
    if not settings.test_mode:
        return settings.challenge_start_date
    if settings.test_start_date is not None:
        return settings.test_start_date
    return local_day_for(now_utc(), settings.tz, settings.day_boundary_hour)


def rules_of(challenge: Challenge, settings: Settings) -> str:
    """Правила не фиксируются в БД при создании челленджа: задание живёт
    в CHALLENGE_TASK, и правка .env должна сразу менять текст правил."""
    if challenge.rules_text:
        return challenge.rules_text
    return texts.rules_text(
        settings.challenge_task,
        challenge.min_duration_sec,
        challenge.max_duration_sec,
        settings.day_boundary_hour,
        settings.daily_code_enabled,
        settings.prizes,
    )
