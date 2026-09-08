"""Задачи по расписанию. Всё время — в таймзоне челленджа.

Рассылок в личку нет: бот не может написать первым тому, кто не нажимал
/start у него в личке, а в беседе есть все. Поэтому слово дня, напоминание
и итоги дня уходят одним постом в общую беседу.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from aiogram import Bot
from aiogram.types import FSInputFile

from bot import texts
from bot.keyboards.training import preview_keyboard
from bot.config import Settings
from bot.db.session import session_scope
from bot.repositories import participations as participations_repo
from bot.repositories import submissions as submissions_repo
from bot.repositories import trainings as trainings_repo
from bot.services import announce as announce_service
from bot.services import backup as backup_service
from bot.services import challenge as challenge_service
from bot.services import checkins as checkins_service
from bot.services import daily_code as daily_code_service
from bot.services import day_close as day_close_service
from bot.services import notifications as notifications_service
from bot.services import submissions as submissions_service
from bot.services import trainings as trainings_service
from bot.services.challenge_day import (
    current_day_number,
    day_end,
    local_day_for,
    month_start,
)
from bot.utils import tg_retry
from bot.utils.timeutil import fmt_time, month_name, now_utc

logger = logging.getLogger(__name__)

# Отчёт о закрытии дня, чтобы итоговый пост знал, у кого прервалась серия:
# после закрытия серии уже обнулены и восстановить этот список из БД нельзя.
# Ключ — клуб: задачи идут по клубам подряд, и один общий слот означал бы,
# что итоги первой группы соберутся по отчёту последней.
_last_report: dict[int | None, day_close_service.CloseReport | None] = {}


def _yesterday(settings: Settings) -> date:
    return local_day_for(now_utc(), settings.tz, settings.day_boundary_hour) - timedelta(days=1)


async def job_generate_code(bot: Bot, settings: Settings) -> None:
    """Через 2 минуты после смены дня — слово на новый день. Сдавать можно
    сразу после границы, поэтому слово нужно раньше утреннего поста."""
    if not settings.daily_code_enabled:
        return
    async with session_scope() as session:
        challenge = await challenge_service.get_current(session, settings)
        if challenge is None:
            return
        day_date = local_day_for(now_utc(), settings.tz, settings.day_boundary_hour)
        await daily_code_service.ensure_code(session, challenge, day_date, settings)


async def job_morning_post(bot: Bot, settings: Settings) -> None:
    """09:00 — пост дня: задание, слово дня, дедлайн, напоминание про зачёт.
    Выходит всегда, даже если слово дня выключено: главное здесь — челлендж."""
    async with session_scope() as session:
        challenge = await challenge_service.get_current(session, settings)
        if challenge is None:
            return
        now = now_utc()
        day_date = local_day_for(now, settings.tz, settings.day_boundary_hour)
        if day_date < challenge.start_date:
            return
        day = current_day_number(
            now, challenge.start_date, settings.tz, settings.day_boundary_hour
        )
        code = await daily_code_service.ensure_code(session, challenge, day_date, settings)

    deadline = fmt_time(day_end(day_date, settings.tz, settings.day_boundary_hour), settings.tz)
    await announce_service.post_to_chat(
        bot,
        settings,
        texts.morning_post(
            day, settings.challenge_task, code, deadline, month_name(day_date.month)
        ),
    )


async def job_reminder(bot: Bot, settings: Settings) -> None:
    """21:00 — напоминание тем, кто ещё не сдал. Здесь пинги уместны."""
    async with session_scope() as session:
        challenge = await challenge_service.get_current(session, settings)
        if challenge is None:
            return
        now = now_utc()
        day_date = local_day_for(now, settings.tz, settings.day_boundary_hour)
        day = current_day_number(now, challenge.start_date, settings.tz, settings.day_boundary_hour)
        if day < 1:
            return

        deadline = fmt_time(day_end(day_date, settings.tz, settings.day_boundary_hour), settings.tz)
        mentions: list[str] = []
        for participation in await participations_repo.list_active(session, challenge.id):
            approved = await submissions_repo.get_approved_for_day(session, participation.id, day)
            if approved is None:
                mentions.append(participation.user.mention_html)

    if not mentions:
        logger.info("Все сдали — напоминание не нужно")
        return
    await announce_service.post_to_chat(bot, settings, texts.reminder(day, deadline, mentions))


async def job_watch_queue(bot: Bot, settings: Settings) -> None:
    """Каждые 10 минут досылает карточки, которые не доехали до судей.

    Пингов по «зависшим» сдачам здесь больше нет. Кружок зачитывается сразу,
    и непросмотренная сдача никого не держит: судья нужен, только чтобы
    отменить зачёт, а это можно сделать когда угодно. Раньше бот подгонял
    судей к границе суток — под авто-зачётом это срочность на пустом месте.
    Карточка без кнопок — другое дело: без неё отменить нечем.
    """
    async with session_scope() as session:
        challenge = await challenge_service.get_current(session, settings)
        if challenge is None:
            return
        await submissions_service.resend_missing_cards(session, bot, settings, challenge.id)


async def job_close_day(bot: Bot, settings: Settings) -> None:
    """На границе суток — фиксация пропусков и обнуление серий за день."""
    async with session_scope() as session:
        _last_report[settings.active_club_id] = await day_close_service.close_day(
            session, settings, _yesterday(settings)
        )


async def job_daily_digest(bot: Bot, settings: Settings) -> None:
    """Сразу после смены дня — итоги вчера постом в беседу."""
    day_date = _yesterday(settings)

    saved = _last_report.get(settings.active_club_id)
    report = saved if saved and saved.day_date == day_date else None
    if report is None:
        # Процесс перезапустили между закрытием и постом — собираем срез заново,
        # без списка прерванных серий.
        logger.info("Отчёт о закрытии дня потерян, собираю итоги из БД")
        async with session_scope() as session:
            report = await day_close_service.build_report(session, settings, day_date)

    if report is None or report.day < 1:
        return

    # Два среза: кто отработал именно вчера и как идут дела за месяц.
    async with session_scope() as session:
        challenge = await challenge_service.get_current(session, settings)
        month_rows = (
            await submissions_repo.leaderboard(session, challenge.id, month_start(day_date))
            if challenge
            else []
        )
        day_rows = (
            await submissions_repo.leaderboard(
                session, challenge.id, since=day_date, until=day_date
            )
            if challenge
            else []
        )

    day_top = [
        texts.day_top_line(i, r.display_name, r.approved)
        for i, r in enumerate([r for r in day_rows if r.approved][:3], start=1)
    ]
    # Месячный урезан до тройки: ниже третьего места всё равно никто себя
    # не ищет, а пост от пяти строк заметно тяжелеет.
    month_top = [
        texts.top_line(i, r.display_name, r.approved, r.current_streak)
        for i, r in enumerate([r for r in month_rows if r.approved][:3], start=1)
    ]

    await day_close_service.post_digest(
        bot,
        settings,
        report,
        month_top=month_top,
        day_top=day_top,
        month=month_name(day_date.month),
    )
    _last_report.pop(settings.active_club_id, None)


async def job_weekly_digest(bot: Bot, settings: Settings) -> None:
    """Суббота, 12:00 — срез за последние 7 дней. Месячный зачёт длинный,
    недельная сводка держит его в поле зрения."""
    async with session_scope() as session:
        challenge = await challenge_service.get_current(session, settings)
        if challenge is None:
            return

        today = local_day_for(now_utc(), settings.tz, settings.day_boundary_hour)
        if today < challenge.start_date:
            return
        since = today - timedelta(days=6)

        rows = await submissions_repo.leaderboard(session, challenge.id, since)
        active = [r for r in rows if r.approved]
        lines = [
            texts.top_line(i, r.display_name, r.approved, r.current_streak)
            for i, r in enumerate(active[:5], start=1)
        ]
        best = max(rows, key=lambda r: r.current_streak, default=None)

    if not lines:
        return
    await announce_service.post_to_chat(
        bot,
        settings,
        texts.weekly_digest(
            lines,
            circles=sum(r.approved for r in active),
            top_streak_name=best.display_name if best else None,
            top_streak=best.current_streak if best else 0,
        ),
    )


async def job_training_reminders(bot: Bot, settings: Settings) -> None:
    """Напоминания тем, кто нажал «Буду». Крутится каждые 10 минут и шлёт
    напоминание, как только до старта осталось меньше N часов."""
    if not settings.training_reminders:
        return

    now = now_utc()
    horizon = now + timedelta(hours=max(settings.training_reminders))
    async with session_scope() as session:
        for training in await trainings_repo.due_reminders(session, now, horizon, club_id=settings.active_club_id):
            left = (training.start_at - now).total_seconds() / 3600
            sent = set(training.reminders_sent or [])
            due = [h for h in settings.training_reminders if left <= h and h not in sent]
            if not due:
                continue

            hours = min(due)  # ближайший рубеж, а не все сразу
            targets = await trainings_repo.going_telegram_ids(session, training.id)
            text = texts.training_reminder(
                club=settings.club_name,
                clock=fmt_time(training.start_at, settings.tz),
                location=training.location or "—",
                training_type=training.training_type,
                hours=hours,
            )
            delivered = 0
            for chat_id in targets:
                if await notifications_service.notify(bot, chat_id, text):
                    delivered += 1

            # Кому бот не смог написать в личку (не жал /start) — тем в чат.
            if settings.trainings_enabled and delivered < len(targets):
                await tg_retry.call_safe(
                    bot.send_message,
                    chat_id=settings.trainings_chat_id,
                    text=text,
                    reply_to_message_id=training.message_id,
                    **settings.trainings_thread,
                )
            for h in due:
                await trainings_repo.mark_reminder_sent(session, training, h)
            logger.info(
                "Напоминание по тренировке #%s: %s из %s в личку",
                training.id, delivered, len(targets),
            )


async def job_training_weather(bot: Bot, settings: Settings) -> None:
    """Утром в день тренировки перезаписываем прогноз и правим пост.

    Прогноз, взятый неделю назад при создании черновика, к делу отношения
    уже не имеет — а в посте он висит как факт.
    """
    if not settings.weather_enabled:
        return

    now = now_utc()
    horizon = now + timedelta(hours=24)
    async with session_scope() as session:
        for training in await trainings_repo.upcoming(
            session, now, until=horizon, only_published=True
        ):
            before = training.weather
            after = await trainings_service.refresh_weather(session, settings, training)
            if after and after != before:
                await session.commit()
                await trainings_service.refresh_post(session, bot, settings, training)
                logger.info("Погода тренировки #%s: %s → %s", training.id, before, after)
        await session.commit()


async def job_checkin_cleanup(bot: Bot, settings: Settings) -> None:
    """Убирает отчёты из ветки тренировок, когда они отслужили своё."""
    async with session_scope() as session:
        await checkins_service.cleanup(session, bot, settings)


async def job_training_auto_draft(bot: Bot, settings: Settings) -> None:
    """Готовит черновик на ближайший вт/чт и присылает админам на правку."""
    async with session_scope() as session:
        draft = await trainings_service.auto_draft(session, settings)
        if draft is None:
            return
        text = trainings_service.render(draft, settings)
        markup = preview_keyboard(draft.id)

    for admin_id in settings.admin_ids:
        await tg_retry.call_safe(
            bot.send_message,
            chat_id=admin_id,
            text="🔁 <b>Черновик по прошлой тренировке</b>\n\n" + text,
            reply_markup=markup,
        )


async def job_backup(bot: Bot, settings: Settings) -> None:
    """04:30 — VACUUM INTO, ротация и отправка первому админу в личку."""
    path = await backup_service.make_backup(
        settings.backup_dir, settings.tz, settings.backup_keep
    )
    admin_id = settings.primary_admin_id
    if admin_id is None:
        return

    size = backup_service.size_mb(path)
    if size > backup_service.MAX_UPLOAD_MB:
        await notifications_service.notify(
            bot,
            admin_id,
            texts.BACKUP_TOO_BIG.format(name=path.name, size=round(size, 1), path=path.parent),
        )
        return

    await tg_retry.call_safe(
        bot.send_document,
        chat_id=admin_id,
        document=FSInputFile(path),
        caption=texts.BACKUP_CAPTION.format(
            date=now_utc().astimezone(settings.tz).strftime("%d.%m.%Y %H:%M")
        ),
    )
