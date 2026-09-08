from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.config import Settings
from bot.db.enums import ParticipationStatus
from bot.db.models import User
from bot.repositories import participations as participations_repo
from bot.services import challenge as challenge_service
from bot.services import daily_code as daily_code_service
from bot.services import stats as stats_service
from bot.services.challenge_day import current_day_number, local_day_for, month_start
from bot.utils.timeutil import month_name, now_utc

router = Router(name="stats")


@router.message(Command("stats"))
async def cmd_stats(
    message: Message, session: AsyncSession, user: User, settings: Settings
) -> None:
    challenge = await challenge_service.get_current(session, settings)
    if challenge is None:
        await message.reply(texts.GENERIC_ERROR)
        return

    participation = await participations_repo.get(session, user.id, challenge.id)
    if participation is None or participation.status != ParticipationStatus.ACTIVE:
        await message.reply(texts.NOT_REGISTERED)
        return

    day = current_day_number(
        now_utc(), challenge.start_date, settings.tz, settings.day_boundary_hour
    )
    if day < 1:
        await message.reply(
            texts.CHALLENGE_NOT_STARTED.format(date=challenge.start_date.strftime("%d.%m.%Y"))
        )
        return

    today = local_day_for(now_utc(), settings.tz, settings.day_boundary_hour)
    since = month_start(today)
    data = await stats_service.build_user_stats(session, participation, day, since)
    await message.reply(
        texts.stats(
            mention=user.mention_html,
            month=month_name(today.month),
            circles_month=data.circles_month,
            circles_total=data.circles_total,
            day=data.day,
            current_streak=data.current_streak,
            best_streak=data.best_streak,
            approved=data.approved,
            rejected=data.rejected,
            missed=data.missed,
            total=data.total,
            percent=data.percent,
            calendar=data.calendar,
        )
        + texts.record_hint(data.current_streak, data.best_streak)
    )


@router.message(Command("top"))
async def cmd_top(
    message: Message, session: AsyncSession, user: User, settings: Settings
) -> None:
    """Основной зачёт — месячный: 1-го числа счёт обнуляется, и у вступивших
    позже есть шанс. Общая таблица живёт в /alltime."""
    today = local_day_for(now_utc(), settings.tz, settings.day_boundary_hour)
    await _send_top(message, session, user, settings, since=month_start(today),
                    month=month_name(today.month))


@router.message(Command("alltime"))
async def cmd_alltime(
    message: Message, session: AsyncSession, user: User, settings: Settings
) -> None:
    await _send_top(message, session, user, settings, since=None, month=None)


async def _send_top(
    message: Message,
    session: AsyncSession,
    user: User,
    settings: Settings,
    *,
    since,
    month: str | None,
) -> None:
    challenge = await challenge_service.get_current(session, settings)
    if challenge is None:
        await message.reply(texts.GENERIC_ERROR)
        return

    entries = await stats_service.build_top(session, challenge.id, limit=10, since=since)
    if not entries or all(e.approved == 0 for e in entries):
        await message.reply(texts.TOP_EMPTY)
        return

    participation = await participations_repo.get(session, user.id, challenge.id)
    my_id = participation.id if participation else None

    lines = [
        texts.top_line(e.place, e.name, e.approved, e.streak, is_me=e.participation_id == my_id)
        for e in entries
    ]
    text = texts.top_header(month) + "\n".join(lines)

    if my_id is not None:
        place = await stats_service.find_place(session, challenge.id, my_id, since)
        if place is not None:
            text += texts.top_my_place(place[0], place[1])

    await message.reply(text)


@router.message(Command("code"))
async def cmd_code(message: Message, session: AsyncSession, settings: Settings) -> None:
    if not settings.daily_code_enabled:
        await message.reply(texts.CODE_DISABLED)
        return

    challenge = await challenge_service.get_current(session, settings)
    if challenge is None:
        await message.reply(texts.GENERIC_ERROR)
        return

    # Слово текущего дня челленджа: в 02:00 это ещё «вчерашнее» слово,
    # если граница суток сдвинута настройкой DAY_BOUNDARY_HOUR.
    day_date = local_day_for(now_utc(), settings.tz, settings.day_boundary_hour)
    day = current_day_number(
        now_utc(), challenge.start_date, settings.tz, settings.day_boundary_hour
    )
    code = await daily_code_service.ensure_code(session, challenge, day_date, settings)
    if code is None:
        await message.reply(texts.CODE_NOT_SET)
        return
    await message.reply(texts.daily_code_current(code, day))
