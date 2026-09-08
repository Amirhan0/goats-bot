from __future__ import annotations

from aiogram import Router

from bot.handlers import (
    admin,
    checkins,
    errors,
    judges,
    start,
    stats,
    submissions,
    trainings_admin,
    trainings_public,
)


def build_router() -> Router:
    """Порядок важен: судейские колбэки и админ-команды разбираются раньше,
    чем общие участниковые хендлеры в личке."""
    router = Router(name="root")
    router.include_router(errors.router)
    router.include_router(admin.migration_router)
    router.include_router(admin.router)
    router.include_router(judges.router)
    router.include_router(start.router)
    router.include_router(stats.router)
    # Тренировки — после команд: у админа в личке свободный текст ловится
    # как «создать тренировку», и он не должен перехватывать команды.
    router.include_router(checkins.router)
    router.include_router(trainings_public.router)
    router.include_router(trainings_admin.router)
    router.include_router(submissions.router)
    router.include_router(errors.fallback_router)
    return router
