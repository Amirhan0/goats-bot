from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

REJECT_REASONS = (
    ("not_strava", "Не скриншот Стравы"),
    ("other_day", "Другой день"),
    ("not_this", "Не эта тренировка"),
    ("unreadable", "Не разобрать"),
)


class CheckinCB(CallbackData, prefix="ci"):
    action: str  # approve | reject_menu | reject | back
    checkin_id: int
    # str | None: пустое хвостовое поле распаковывается как None, и при
    # строгом типе фильтр молча перестаёт совпадать.
    reason: str | None = None


def checkin_keyboard(checkin_id: int) -> InlineKeyboardMarkup:
    """Одна кнопка: приход уже засчитан, подтверждать нечего.

    Кнопка «Засчитать» осталась бы обманом — она ничего не меняла бы.
    Судья нужен, только когда отчёт не годится.
    """
    builder = InlineKeyboardBuilder()
    builder.button(
        text="❌ Отменить зачёт",
        callback_data=CheckinCB(action="reject_menu", checkin_id=checkin_id),
    )
    return builder.as_markup()


def checkin_reasons_keyboard(checkin_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for key, label in REJECT_REASONS:
        builder.button(
            text=label, callback_data=CheckinCB(action="reject", checkin_id=checkin_id, reason=key)
        )
    builder.button(text="◀️ Назад", callback_data=CheckinCB(action="back", checkin_id=checkin_id))
    builder.adjust(2)
    return builder.as_markup()


REASON_TEXTS = dict(REJECT_REASONS)
