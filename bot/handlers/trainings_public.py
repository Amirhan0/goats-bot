"""Что видят обычные участники: кнопки под постом и расписание."""

from __future__ import annotations

from datetime import timedelta

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.config import Settings
from bot.db.enums import RsvpStatus
from bot.db.models import User
from bot.keyboards.training import RsvpCB
from bot.repositories import trainings as trainings_repo
from bot.repositories import users as users_repo
from bot.services import trainings as trainings_service
from bot.utils.timeutil import fmt_time, format_day_with_weekday, now_utc

router = Router(name="trainings_public")


@router.poll_answer()
async def on_poll_answer(
    poll_answer, session: AsyncSession, settings: Settings
) -> None:  # noqa: ANN001
    """Голос в опросе = ответ на сбор.

    Свою таблицу ведём отдельно от Telegram: по ней шлются напоминания
    и считается статистика, а список голосовавших из опроса не выгрузишь.
    """
    training = await trainings_repo.get_by_poll(session, poll_answer.poll_id)
    if training is None:
        return

    voter = poll_answer.user
    if voter is None:  # голос от имени канала — привязать не к кому
        return

    user = await users_repo.get_or_create(
        session,
        telegram_id=voter.id,
        username=voter.username,
        first_name=voter.first_name or "",
    )
    await trainings_service.apply_poll_answer(
        session, training, user.id, list(poll_answer.option_ids or [])
    )
    await session.commit()


@router.callback_query(RsvpCB.filter())
async def cb_rsvp(
    callback: CallbackQuery,
    callback_data: RsvpCB,
    bot: Bot,
    session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    """Ответ можно менять сколько угодно — актуальный всегда один."""
    training = await trainings_repo.get(session, callback_data.training_id)
    if training is None:
        await callback.answer(texts.TRAINING_NOT_FOUND, show_alert=True)
        return
    try:
        status = RsvpStatus(callback_data.status or "")
    except ValueError:
        await callback.answer()
        return

    label = await trainings_service.set_rsvp(
        session, bot, settings, training, user.id, status
    )
    await callback.answer(label)


async def _training_lines(session: AsyncSession, items, settings: Settings) -> list[str]:
    lines = []
    for training in items:
        counts = await trainings_repo.counts(session, training.id)
        lines.append(
            texts.training_line(
                day=format_day_with_weekday(training.start_at, settings.tz),
                clock=fmt_time(training.start_at, settings.tz),
                location=training.location or "—",
                training_type=training.training_type,
                going=counts.get("going", 0),
            )
        )
    return lines


@router.message(Command("next"))
async def cmd_next(message: Message, session: AsyncSession, settings: Settings) -> None:
    items = await trainings_repo.upcoming(
        session, now_utc(), limit=1, only_published=True, club_id=settings.active_club_id
    )
    if not items:
        await message.reply(texts.TRAINING_EMPTY_LIST)
        return
    await message.reply(trainings_service.render(items[0], settings))


@router.message(Command("schedule"))
async def cmd_schedule(message: Message, session: AsyncSession, settings: Settings) -> None:
    now = now_utc()
    items = await trainings_repo.upcoming(
        session,
        now,
        until=now + timedelta(days=7),
        only_published=True,
        club_id=settings.active_club_id,
    )
    if not items:
        await message.reply(texts.TRAINING_EMPTY_LIST)
        return
    lines = await _training_lines(session, items, settings)
    await message.reply("<b>🗓 Ближайшие 7 дней</b>\n\n" + "\n".join(lines))


@router.message(Command("past"))
async def cmd_past(message: Message, session: AsyncSession, settings: Settings) -> None:
    items = await trainings_repo.past(session, now_utc(), limit=10, club_id=settings.active_club_id)
    if not items:
        await message.reply(texts.TRAINING_EMPTY_LIST)
        return
    lines = await _training_lines(session, items, settings)
    await message.reply("<b>📚 Прошедшие тренировки</b>\n\n" + "\n".join(lines))


@router.message(Command("mytrainings"))
async def cmd_my_trainings(message: Message, session: AsyncSession, user: User) -> None:
    history = await trainings_repo.user_history(session, user.id)
    await message.reply(
        texts.my_training_stats(
            going=history.get("going", 0),
            maybe=history.get("maybe", 0),
            skipped=history.get("not_going", 0),
        )
    )


@router.message(F.chat.type == "private", F.text.lower().regexp(r"кто\s+(идёт|идет|будет)"))
async def cmd_who_is_going(message: Message, session: AsyncSession, settings: Settings) -> None:
    """«Кто идёт?» обычным текстом — как просили в ТЗ."""
    items = await trainings_repo.upcoming(session, now_utc(), limit=1, club_id=settings.active_club_id)
    if not items:
        await message.reply(texts.TRAINING_EMPTY_LIST)
        return
    await message.reply(
        await trainings_service.participants_text(session, items[0], settings)
    )
