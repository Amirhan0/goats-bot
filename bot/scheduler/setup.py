from __future__ import annotations

import logging

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from bot.config import Settings, settings_for_club
from bot.db.session import session_scope
from bot.repositories import clubs as clubs_repo
from bot.scheduler import jobs

logger = logging.getLogger(__name__)


def per_club(func):
    """Гоняет задачу по каждому активному клубу с его настройками.

    Сами задачи о клубах ничего не знают: они спрашивают у Settings, куда
    постить и какой челлендж текущий, а тут им подсовывают клубную копию.
    Если клубов нет вовсе (свежая установка), работаем по .env, как раньше.
    """

    async def runner(bot: Bot, settings: Settings) -> None:
        async with session_scope() as session:
            clubs = await clubs_repo.list_active(session)
        if not clubs:
            await func(bot, settings)
            return
        for club in clubs:
            try:
                await func(bot, settings_for_club(settings, club))
            except Exception:  # noqa: BLE001 — падение одного клуба не должно
                logger.exception(  # ронять остальные
                    "Задача %s упала на клубе #%s", func.__name__, club.id
                )

    runner.__name__ = func.__name__
    return runner


def build_scheduler(bot: Bot, settings: Settings) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=settings.tz)
    boundary = settings.day_boundary_hour

    def cron(**kwargs: object) -> CronTrigger:
        """Зона указывается ЯВНО. Готовому объекту CronTrigger APScheduler свою
        зону не навязывает — он берёт системную. На сервере в UTC это молча
        сдвигало всё расписание на пять часов."""
        return CronTrigger(timezone=settings.tz, **kwargs)  # type: ignore[arg-type]

    schedule = (
        ("close_day", per_club(jobs.job_close_day), cron(hour=boundary, minute=0)),
        ("generate_code", per_club(jobs.job_generate_code), cron(hour=boundary, minute=2)),
        ("daily_digest", per_club(jobs.job_daily_digest), cron(hour=boundary, minute=5)),
        # Бэкап не по клубам: база одна на всех.
        ("backup", jobs.job_backup, cron(hour=boundary, minute=30)),
        ("morning_post", per_club(jobs.job_morning_post), cron(hour=9, minute=0)),
        ("reminder", per_club(jobs.job_reminder), cron(hour=21, minute=0)),
        ("weekly_digest", per_club(jobs.job_weekly_digest), cron(day_of_week="sat", hour=12)),
        # Не по крону: очередь надо разгребать в течение дня, а не в фиксированный час.
        ("watch_queue", per_club(jobs.job_watch_queue), IntervalTrigger(minutes=10)),
        # Напоминания о тренировках: рубежи заданы в часах, поэтому проверяем
        # часто и шлём, как только рубеж пройден.
        ("training_reminders", per_club(jobs.job_training_reminders), IntervalTrigger(minutes=10)),
        ("training_draft", per_club(jobs.job_training_auto_draft), cron(hour=10, minute=0)),
        # Прогноз недельной давности врёт — обновляем утром в день тренировки.
        ("training_weather", per_club(jobs.job_training_weather), cron(hour=8, minute=0)),
        ("checkin_cleanup", per_club(jobs.job_checkin_cleanup), cron(hour=5, minute=0)),
    )

    for job_id, func, trigger in schedule:
        scheduler.add_job(
            func,
            trigger=trigger,
            id=job_id,
            args=(bot, settings),
            # Если процесс лежал, догоняем задачу в течение часа, но один раз.
            misfire_grace_time=3600,
            coalesce=True,
            max_instances=1,
        )

    logger.info("Планировщик собран: %s задач, зона %s", len(schedule), settings.timezone)
    return scheduler
