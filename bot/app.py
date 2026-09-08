from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
)

from bot.config import Settings, settings_for_club, get_settings
from bot.db.session import dispose_engine, get_sessionmaker, init_engine, session_scope
from bot.handlers import build_router
from bot.logging_conf import setup_logging
from bot.middlewares.auth import UserMiddleware
from bot.middlewares.club import ClubMiddleware
from bot.repositories import clubs as clubs_repo
from bot.middlewares.db import DbSessionMiddleware
from bot.middlewares.logging import UpdateLoggingMiddleware
from bot.middlewares.throttling import VideoNoteThrottleMiddleware
from bot.scheduler.setup import build_scheduler
from bot.services import challenge as challenge_service

logger = logging.getLogger(__name__)

COMMANDS = (
    ("start", "Присоединиться к челленджу"),
    ("stats", "Моя статистика"),
    ("top", "Топ месяца"),
    ("alltime", "Топ за всё время"),
    ("code", "Слово дня"),
    ("rules", "Правила"),
    ("judges", "Кто судит"),
    ("next", "Ближайшая тренировка"),
    ("schedule", "Расписание на 7 дней"),
    ("attendance", "Рейтинг приходов"),
    ("help", "Все команды"),
    ("leave", "Выйти из челленджа"),
)


def build_dispatcher(settings: Settings) -> Dispatcher:
    dispatcher = Dispatcher(storage=MemoryStorage())

    # Порядок outer-мидлварей = порядок исполнения. Сессия и пользователь
    # должны попасть в data до фильтров (IsAdmin/IsJudge их читают).
    dispatcher.update.outer_middleware(UpdateLoggingMiddleware())
    dispatcher.update.outer_middleware(DbSessionMiddleware(get_sessionmaker()))
    dispatcher.update.outer_middleware(UserMiddleware(settings))
    # После UserMiddleware: в личке клуб выбирается по роли, а для этого
    # нужен уже загруженный User.
    dispatcher.update.outer_middleware(ClubMiddleware())
    dispatcher.message.outer_middleware(
        VideoNoteThrottleMiddleware(settings.submission_cooldown_sec)
    )

    dispatcher.include_router(build_router())
    return dispatcher


async def on_startup(bot: Bot, settings: Settings) -> None:
    async with session_scope() as session:
        # Клуб по умолчанию собирается из .env — так свежая установка
        # поднимается без ручной настройки, а существующая уже перенесена
        # миграцией 0011.
        club = await clubs_repo.get_by_chat(session, settings.participants_chat_id)
        if club is None and settings.participants_chat_id:
            club = await clubs_repo.create(
                session,
                title=settings.club_name,
                chat_id=settings.participants_chat_id,
                participants_thread_id=settings.participants_thread_id,
                trainings_thread_id=settings.trainings_thread_id,
                checkins_thread_id=settings.checkins_thread_id,
                judges_chat_id=settings.judges_chat_id,
                judge_ids=list(settings.judge_ids),
                admin_ids=list(settings.admin_ids),
            )
            logger.info("Создан клуб по умолчанию #%s «%s»", club.id, club.title)

        scoped = settings_for_club(settings, club) if club else settings
        challenge = await challenge_service.ensure_current(session, scoped)
        logger.info(
            "Активный челлендж: #%s «%s», старт %s, режим %s",
            challenge.id,
            challenge.title,
            challenge.start_date,
            "ТЕСТОВЫЙ" if settings.test_mode else "боевой",
        )

    commands = [BotCommand(command=c, description=d) for c, d in COMMANDS]
    # Команды нужны и в беседе: основная жизнь челленджа происходит там.
    await bot.set_my_commands(commands, scope=BotCommandScopeAllPrivateChats())
    await bot.set_my_commands(commands, scope=BotCommandScopeAllGroupChats())

    me = await bot.get_me()
    logger.info(
        "Бот @%s запущен. Беседа: %s, судьи: %s, задание: %s",
        me.username,
        settings.participants_chat_id,
        settings.judges_chat_id,
        settings.challenge_task,
    )
    if not await _can_see_messages(bot):
        logger.warning(
            "У бота включён privacy mode — он НЕ увидит кружки в беседе. "
            "Исправить: @BotFather -> /setprivacy -> Disable, затем перезайти в беседу."
        )


async def _can_see_messages(bot: Bot) -> bool:
    """can_read_all_group_messages — это и есть выключенный privacy mode.
    Самая частая причина «бот не реагирует на кружки в беседе»."""
    me = await bot.get_me()
    return bool(getattr(me, "can_read_all_group_messages", False))


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    init_engine(settings.db_url)

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = build_dispatcher(settings)
    scheduler = build_scheduler(bot, settings)

    await on_startup(bot, settings)
    scheduler.start()

    try:
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    except asyncio.CancelledError:
        logger.info("Получен сигнал остановки")
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()
        await dispose_engine()
        logger.info("Бот остановлен")
