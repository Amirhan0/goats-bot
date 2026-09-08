"""Админ создаёт и ведёт тренировки в личке бота."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.config import Settings
from bot.db.enums import AuditAction, TrainingStatus
from bot.db.models import Training, User
from bot.filters import IsAdmin
from bot.keyboards.training import (
    TrainingCB,
    confirm_purge_keyboard,
    edit_fields_keyboard,
    list_keyboard,
    manage_keyboard,
    preview_keyboard,
)
from bot.repositories import checkins as checkins_repo
from bot.repositories import audit as audit_repo
from bot.repositories import trainings as trainings_repo
from bot.services import trainings as trainings_service
from bot.services.training_parse import parse
from bot.utils.timeutil import fmt_time, format_day_with_weekday, now_utc

logger = logging.getLogger(__name__)

router = Router(name="trainings_admin")
router.message.filter(IsAdmin(), F.chat.type == "private")
router.callback_query.filter(IsAdmin())


class TrainingForm(StatesGroup):
    date = State()
    time = State()
    location = State()
    type = State()
    description = State()
    edit_value = State()


MENU = (
    ("➕ Создать тренировку", "create"),
    ("📅 Ближайшие", "upcoming"),
    ("📝 Черновики", "drafts"),
    ("📚 Прошедшие", "history"),
)


def _label(training: Training, settings: Settings) -> str:
    mark = {"draft": "📝", "published": "📢", "cancelled": "🚫"}[training.status.value]
    return (
        f"{mark} {format_day_with_weekday(training.start_at, settings.tz)}, "
        f"{fmt_time(training.start_at, settings.tz)} — {training.location or '—'}"
    )


async def _show_card(
    target: Message, session: AsyncSession, training: Training, settings: Settings
) -> None:
    await target.answer(
        trainings_service.render(training, settings),
        reply_markup=manage_keyboard(
            training.id,
            published=bool(training.message_id),
            reminders=training.reminders_enabled,
        ),
    )


@router.message(Command("trainings"))
async def cmd_trainings(message: Message) -> None:
    await message.answer(
        "<b>🏃 Тренировки</b>\n\n" + texts.TRAINING_ASK_FREEFORM,
        reply_markup=_menu_keyboard(),
    )


def _menu_keyboard():
    builder = InlineKeyboardBuilder()
    for label, action in MENU:
        builder.button(text=label, callback_data=TrainingCB(action=action))
    builder.adjust(1)
    return builder.as_markup()


# ── списки ───────────────────────────────────────────────────────


@router.callback_query(TrainingCB.filter(F.action.in_({"upcoming", "drafts", "history"})))
async def cb_lists(
    callback: CallbackQuery, callback_data: TrainingCB, session: AsyncSession, settings: Settings
) -> None:
    now = now_utc()
    if callback_data.action == "drafts":
        items, title = await trainings_repo.drafts(session, club_id=settings.active_club_id), "📝 Черновики"
    elif callback_data.action == "history":
        items, title = await trainings_repo.past(session, now, club_id=settings.active_club_id), "📚 Прошедшие"
    else:
        items, title = await trainings_repo.upcoming(session, now, club_id=settings.active_club_id), "📅 Ближайшие"

    await callback.answer()
    if not items:
        await callback.message.answer(f"<b>{title}</b>\n\n{texts.TRAINING_EMPTY_LIST}")
        return
    await callback.message.answer(
        f"<b>{title}</b>",
        reply_markup=list_keyboard([(t.id, _label(t, settings)) for t in items]),
    )


@router.callback_query(TrainingCB.filter(F.action == "open"))
async def cb_open(
    callback: CallbackQuery, callback_data: TrainingCB, session: AsyncSession, settings: Settings
) -> None:
    training = await trainings_repo.get(session, callback_data.training_id)
    await callback.answer()
    if training is None:
        await callback.message.answer(texts.TRAINING_NOT_FOUND)
        return
    await _show_card(callback.message, session, training, settings)


# ── создание ─────────────────────────────────────────────────────


@router.callback_query(TrainingCB.filter(F.action == "create"))
async def cb_create(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(TrainingForm.date)
    await callback.answer()
    await callback.message.answer(texts.TRAINING_ASK_DATE)


@router.message(StateFilter(None), F.text, ~F.text.startswith("/"))
async def on_freeform(
    message: Message, session: AsyncSession, user: User, settings: Settings
) -> None:
    """Админ пишет тренировку одной строкой — самый быстрый путь."""
    parsed = parse(message.text, settings.tz, now_utc())
    if parsed.start_at is None or not parsed.location:
        await message.answer(texts.training_parse_failed(parsed.missing))
        return

    training = await trainings_repo.create(
        session,
        title="",
        description=parsed.description,
        training_type=parsed.training_type,
        location=parsed.location,
        start_at=parsed.start_at,
        created_by=user.id,
        club_id=settings.active_club_id,
        status=TrainingStatus.DRAFT,
        reminders_enabled=True,
        reminders_sent=[],
    )
    await audit_repo.log(
        session, actor_id=user.telegram_id, action=AuditAction.TRAINING_CREATED,
        target_type="training", target_id=training.id,
    )
    await message.answer(
        trainings_service.render(training, settings) + texts.TRAINING_PREVIEW_HINT,
        reply_markup=preview_keyboard(training.id),
    )


# ── пошаговый мастер ─────────────────────────────────────────────


@router.message(StateFilter(TrainingForm.date), F.text)
async def step_date(message: Message, state: FSMContext, settings: Settings) -> None:
    parsed = parse(message.text, settings.tz, now_utc())
    if parsed.day is None:
        await message.answer(texts.TRAINING_BAD_DATE)
        return
    await state.update_data(day=parsed.day.isoformat())
    await state.set_state(TrainingForm.time)
    await message.answer(texts.TRAINING_ASK_TIME)


@router.message(StateFilter(TrainingForm.time), F.text)
async def step_time(message: Message, state: FSMContext, settings: Settings) -> None:
    parsed = parse(message.text, settings.tz, now_utc())
    if parsed.clock is None:
        await message.answer(texts.TRAINING_BAD_TIME)
        return
    await state.update_data(clock=parsed.clock.isoformat())
    await state.set_state(TrainingForm.location)
    await message.answer(texts.TRAINING_ASK_LOCATION)


@router.message(StateFilter(TrainingForm.location), F.text)
async def step_location(message: Message, state: FSMContext) -> None:
    await state.update_data(location=message.text.strip())
    await state.set_state(TrainingForm.type)
    await message.answer(texts.TRAINING_ASK_TYPE)


@router.message(StateFilter(TrainingForm.type), F.text)
async def step_type(message: Message, state: FSMContext) -> None:
    await state.update_data(training_type=message.text.strip())
    await state.set_state(TrainingForm.description)
    await message.answer(texts.TRAINING_ASK_DESCRIPTION)


@router.message(StateFilter(TrainingForm.description), F.text)
async def step_description(
    message: Message, state: FSMContext, session: AsyncSession, user: User, settings: Settings
) -> None:
    data = await state.get_data()
    await state.clear()

    description = "" if message.text.strip() in {"-", "—", "нет"} else message.text.strip()
    start_at = datetime.combine(
        datetime.fromisoformat(data["day"]).date(),
        datetime.fromisoformat(f"2000-01-01T{data['clock']}").time(),
        tzinfo=settings.tz,
    )
    training = await trainings_repo.create(
        session,
        title="",
        description=description,
        training_type=data.get("training_type", ""),
        location=data.get("location", ""),
        start_at=start_at,
        created_by=user.id,
        club_id=settings.active_club_id,
        status=TrainingStatus.DRAFT,
        reminders_enabled=True,
        reminders_sent=[],
    )
    await message.answer(
        trainings_service.render(training, settings) + texts.TRAINING_PREVIEW_HINT,
        reply_markup=preview_keyboard(training.id),
    )


# ── действия над тренировкой ─────────────────────────────────────


@router.callback_query(TrainingCB.filter(F.action == "publish"))
async def cb_publish(
    callback: CallbackQuery,
    callback_data: TrainingCB,
    bot: Bot,
    session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    training = await trainings_repo.get(session, callback_data.training_id)
    if training is None:
        await callback.answer(texts.TRAINING_NOT_FOUND, show_alert=True)
        return

    result = await trainings_service.publish(session, bot, settings, training, user.telegram_id)
    await session.commit()
    await callback.answer(result.message, show_alert=not result.ok)
    if result.ok:
        await callback.message.edit_reply_markup(
            reply_markup=manage_keyboard(training.id, True, training.reminders_enabled)
        )


@router.callback_query(TrainingCB.filter(F.action == "republish"))
async def cb_republish(
    callback: CallbackQuery,
    callback_data: TrainingCB,
    bot: Bot,
    session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    """Поднять пост наверх ветки: старый убираем, новый шлём следом."""
    training = await trainings_repo.get(session, callback_data.training_id)
    if training is None:
        await callback.answer(texts.TRAINING_NOT_FOUND, show_alert=True)
        return

    result = await trainings_service.republish(
        session, bot, settings, training, user.telegram_id
    )
    await session.commit()
    # show_alert даже при успехе: про обнулившийся опрос надо прочитать,
    # а всплывашка на две секунды такое не доносит.
    await callback.answer(result.message, show_alert=True)


@router.callback_query(TrainingCB.filter(F.action == "weather"))
async def cb_weather(
    callback: CallbackQuery,
    callback_data: TrainingCB,
    bot: Bot,
    session: AsyncSession,
    settings: Settings,
) -> None:
    training = await trainings_repo.get(session, callback_data.training_id)
    if training is None:
        await callback.answer(texts.TRAINING_NOT_FOUND, show_alert=True)
        return

    text = await trainings_service.refresh_weather(session, settings, training)
    await session.commit()
    if not text:
        await callback.answer(texts.WEATHER_UNAVAILABLE, show_alert=True)
        return

    await callback.answer(text)
    if training.message_id:
        await trainings_service.refresh_post(session, bot, settings, training)
    await _show_card(callback.message, session, training, settings)


@router.callback_query(TrainingCB.filter(F.action == "who"))
async def cb_who(
    callback: CallbackQuery, callback_data: TrainingCB, session: AsyncSession, settings: Settings
) -> None:
    training = await trainings_repo.get(session, callback_data.training_id)
    await callback.answer()
    if training is None:
        await callback.message.answer(texts.TRAINING_NOT_FOUND)
        return
    await callback.message.answer(
        await trainings_service.participants_text(session, training, settings)
    )


@router.callback_query(TrainingCB.filter(F.action == "reminders"))
async def cb_reminders(
    callback: CallbackQuery, callback_data: TrainingCB, session: AsyncSession
) -> None:
    training = await trainings_repo.get(session, callback_data.training_id)
    if training is None:
        await callback.answer(texts.TRAINING_NOT_FOUND, show_alert=True)
        return
    training.reminders_enabled = not training.reminders_enabled
    await session.commit()
    await callback.answer(
        texts.TRAINING_REMINDERS_ON if training.reminders_enabled else texts.TRAINING_REMINDERS_OFF
    )
    await callback.message.edit_reply_markup(
        reply_markup=manage_keyboard(
            training.id, bool(training.message_id), training.reminders_enabled
        )
    )


@router.callback_query(TrainingCB.filter(F.action == "delete"))
async def cb_delete(
    callback: CallbackQuery,
    callback_data: TrainingCB,
    bot: Bot,
    session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    """Опубликованную не удаляем молча — помечаем отменённой и правим пост,
    иначе в чате останется приглашение на несуществующую тренировку."""
    training = await trainings_repo.get(session, callback_data.training_id)
    if training is None:
        await callback.answer(texts.TRAINING_NOT_FOUND, show_alert=True)
        return

    if training.message_id:
        training.status = TrainingStatus.CANCELLED
        await session.commit()
        await trainings_service.refresh_post(session, bot, settings, training)
        await trainings_service.stop_poll(bot, settings, training)
        message = texts.TRAINING_CANCELLED
        action = AuditAction.TRAINING_CANCELLED
    else:
        await trainings_repo.remove(session, training.id)
        message = texts.TRAINING_DELETED
        action = AuditAction.TRAINING_CANCELLED

    await audit_repo.log(
        session, actor_id=user.telegram_id, action=action,
        target_type="training", target_id=callback_data.training_id,
    )
    await session.commit()
    await callback.answer(message)
    await callback.message.edit_reply_markup(reply_markup=None)


@router.callback_query(TrainingCB.filter(F.action == "purge"))
async def cb_purge(
    callback: CallbackQuery,
    callback_data: TrainingCB,
    session: AsyncSession,
    settings: Settings,
) -> None:
    """Спрашиваем до удаления: вместе с постом уходят приходы, а вернуть
    их потом неоткуда."""
    training = await trainings_repo.get(session, callback_data.training_id)
    if training is None:
        await callback.answer(texts.TRAINING_NOT_FOUND, show_alert=True)
        return

    checkins = await checkins_repo.list_for_training(session, training.id)
    await callback.message.edit_text(
        texts.training_purge_confirm(
            format_day_with_weekday(training.start_at, settings.tz),
            fmt_time(training.start_at, settings.tz),
            len(checkins),
        ),
        reply_markup=confirm_purge_keyboard(training.id),
    )
    await callback.answer()


@router.callback_query(TrainingCB.filter(F.action == "purge_yes"))
async def cb_purge_yes(
    callback: CallbackQuery,
    callback_data: TrainingCB,
    bot: Bot,
    session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    training = await trainings_repo.get(session, callback_data.training_id)
    if training is None:
        await callback.answer(texts.TRAINING_NOT_FOUND, show_alert=True)
        return

    # Лог до удаления: после него training_id уже ни на что не сошлётся.
    await audit_repo.log(
        session, actor_id=user.telegram_id, action=AuditAction.TRAINING_CANCELLED,
        target_type="training", target_id=training.id,
        payload={"purged": True},
    )
    removed = await trainings_service.purge(session, bot, settings, training)

    await callback.message.edit_text(texts.training_purged(removed), reply_markup=None)
    await callback.answer()


@router.callback_query(TrainingCB.filter(F.action == "repeat"))
async def cb_repeat(
    callback: CallbackQuery,
    callback_data: TrainingCB,
    session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    """Повтор: то же место и тип, дата — через неделю. Дальше правим время."""
    source = await trainings_repo.get(session, callback_data.training_id)
    if source is None:
        await callback.answer(texts.TRAINING_NOT_FOUND, show_alert=True)
        return

    copy = await trainings_service.copy_for_repeat(
        session, source, source.start_at + timedelta(days=7), user.id
    )
    await session.commit()
    await callback.answer("Скопировано на следующую неделю")
    await callback.message.answer(
        trainings_service.render(copy, settings) + texts.TRAINING_PREVIEW_HINT,
        reply_markup=preview_keyboard(copy.id),
    )


# ── редактирование ───────────────────────────────────────────────


@router.callback_query(TrainingCB.filter(F.action == "edit"))
async def cb_edit(callback: CallbackQuery, callback_data: TrainingCB) -> None:
    await callback.answer()
    await callback.message.answer(
        "Что меняем?", reply_markup=edit_fields_keyboard(callback_data.training_id)
    )


@router.callback_query(TrainingCB.filter(F.action == "set"))
async def cb_set_field(
    callback: CallbackQuery, callback_data: TrainingCB, state: FSMContext
) -> None:
    prompts = {
        "date": texts.TRAINING_ASK_DATE,
        "time": texts.TRAINING_ASK_TIME,
        "weather": texts.TRAINING_ASK_WEATHER,
        "plan": texts.TRAINING_ASK_PLAN,
        "gear": texts.TRAINING_ASK_GEAR,
        "location": texts.TRAINING_ASK_LOCATION,
        "url": texts.TRAINING_ASK_URL,
        "notes": texts.TRAINING_ASK_NOTES,
        "description": texts.TRAINING_ASK_DESCRIPTION,
    }
    await state.set_state(TrainingForm.edit_value)
    await state.update_data(training_id=callback_data.training_id, field=callback_data.field)
    await callback.answer()
    await callback.message.answer(prompts.get(callback_data.field or "", "Новое значение?"))


@router.message(StateFilter(TrainingForm.edit_value), F.text)
async def on_edit_value(
    message: Message,
    state: FSMContext,
    bot: Bot,
    session: AsyncSession,
    settings: Settings,
) -> None:
    data = await state.get_data()
    training = await trainings_repo.get(session, int(data["training_id"]))
    if training is None:
        await state.clear()
        await message.answer(texts.TRAINING_NOT_FOUND)
        return

    field, value = data.get("field"), message.text.strip()
    local = training.start_at.astimezone(settings.tz)

    if field == "date":
        parsed = parse(value, settings.tz, now_utc())
        if parsed.day is None:
            await message.answer(texts.TRAINING_BAD_DATE)
            return
        training.start_at = datetime.combine(parsed.day, local.time(), tzinfo=settings.tz)
    elif field == "time":
        parsed = parse(value, settings.tz, now_utc())
        if parsed.clock is None:
            await message.answer(texts.TRAINING_BAD_TIME)
            return
        training.start_at = datetime.combine(local.date(), parsed.clock, tzinfo=settings.tz)
    else:
        empty = value in {"-", "—", "нет"}
        column = {
            "location": "location",
            "url": "location_url",
            "weather": "weather",
            "plan": "plan",
            "gear": "gear",
            "notes": "notes",
            "type": "training_type",
        }.get(field or "", "description")
        setattr(training, column, "" if empty else value)

    await session.commit()
    await state.clear()

    # Пост в чате перезаписываем, а не создаём новый.
    if training.message_id:
        await trainings_service.refresh_post(session, bot, settings, training)
    await _show_card(message, session, training, settings)
