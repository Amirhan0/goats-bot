from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot import texts


class RsvpCB(CallbackData, prefix="rsvp"):
    training_id: int
    # str | None, а не str: пустое хвостовое поле unpack превращает в None,
    # и при строгом типе фильтр молча перестаёт совпадать.
    status: str | None = None


class TrainingCB(CallbackData, prefix="tr"):
    # publish | republish | edit | delete | purge | purge_yes | who | reminders | repeat | open
    action: str
    training_id: int = 0
    field: str | None = None


def rsvp_keyboard(training_id: int, counts: dict[str, int]) -> InlineKeyboardMarkup:
    """Счётчик прямо на кнопках — видно, сколько собралось, без лишних сообщений."""
    builder = InlineKeyboardBuilder()
    for key in ("going", "maybe", "not_going"):
        builder.button(
            text=f"{texts.RSVP_LABELS[key]} — {counts.get(key, 0)}",
            callback_data=RsvpCB(training_id=training_id, status=key),
        )
    builder.adjust(1)
    return builder.as_markup()


def preview_keyboard(training_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Опубликовать", callback_data=TrainingCB(action="publish", training_id=training_id))
    builder.button(text="✏️ Редактировать", callback_data=TrainingCB(action="edit", training_id=training_id))
    builder.button(text="❌ Отменить", callback_data=TrainingCB(action="delete", training_id=training_id))
    builder.adjust(1)
    return builder.as_markup()


def manage_keyboard(training_id: int, published: bool, reminders: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    # Опубликовать можно и повторно: пост уезжает вверх, и его поднимают заново.
    builder.button(
        text="🔄 Опубликовать заново" if published else "📢 Опубликовать",
        callback_data=TrainingCB(
            action="republish" if published else "publish", training_id=training_id
        ),
    )
    builder.button(text="✏️ Редактировать", callback_data=TrainingCB(action="edit", training_id=training_id))
    builder.button(text="🌦️ Обновить погоду", callback_data=TrainingCB(action="weather", training_id=training_id))
    builder.button(text="👥 Участники", callback_data=TrainingCB(action="who", training_id=training_id))
    builder.button(
        text="🔕 Выключить напоминания" if reminders else "🔔 Включить напоминания",
        callback_data=TrainingCB(action="reminders", training_id=training_id),
    )
    builder.button(text="🔁 Повторить", callback_data=TrainingCB(action="repeat", training_id=training_id))
    if published:
        # Отмена и удаление — разные вещи. Отменённая остаётся в чате с пометкой
        # «🚫 ОТМЕНЕНА», чтобы пришедшие поняли, почему сбора нет. Удаление
        # стирает пост целиком — на случай, когда тренировку завели по ошибке.
        builder.button(
            text="🚫 Отменить", callback_data=TrainingCB(action="delete", training_id=training_id)
        )
    builder.button(
        text="🗑 Удалить", callback_data=TrainingCB(action="purge", training_id=training_id)
    )
    builder.adjust(1)
    return builder.as_markup()


def confirm_purge_keyboard(training_id: int) -> InlineKeyboardMarkup:
    """Удаление необратимо и уносит с собой приходы — переспрашиваем."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🗑 Да, удалить", callback_data=TrainingCB(action="purge_yes", training_id=training_id)
    )
    builder.button(
        text="◀️ Отмена", callback_data=TrainingCB(action="open", training_id=training_id)
    )
    builder.adjust(1)
    return builder.as_markup()


def edit_fields_keyboard(training_id: int) -> InlineKeyboardMarkup:
    fields = (
        ("date", "📅 Дата"),
        ("time", "🕒 Время"),
        ("weather", "🌦️ Погода"),
        ("plan", "📋 План"),
        ("gear", "🎒 Что взять"),
        ("location", "📍 Место"),
        ("url", "🔗 Ссылка"),
        ("notes", "❗️ Заметки"),
    )
    builder = InlineKeyboardBuilder()
    for key, label in fields:
        builder.button(
            text=label, callback_data=TrainingCB(action="set", training_id=training_id, field=key)
        )
    builder.button(text="◀️ Готово", callback_data=TrainingCB(action="open", training_id=training_id))
    builder.adjust(2)
    return builder.as_markup()


def list_keyboard(items: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for training_id, label in items:
        builder.button(text=label, callback_data=TrainingCB(action="open", training_id=training_id))
    builder.adjust(1)
    return builder.as_markup()
