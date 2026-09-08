from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.db.enums import RejectReason
from bot.texts import REJECT_REASON_TEXTS


class VerdictCB(CallbackData, prefix="v"):
    action: str  # approve | reject_menu | reject | back
    submission_id: int
    # Именно `str | None`, а не `str`: пустое хвостовое поле распаковывается
    # как None, и при типе `str` unpack падает валидацией. Ошибку фильтр
    # глотает молча — кнопка просто перестаёт работать без следов в логах.
    reason: str | None = None


def verdict_keyboard(submission_id: int) -> InlineKeyboardMarkup:
    """Одна кнопка: кружок уже в зачёте, подтверждать нечего.

    Обработчик action="approve" при этом жив — карточки со старой кнопкой
    висят в чате судей и должны продолжать работать.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❌ Отменить зачёт",
                    callback_data=VerdictCB(
                        action="reject_menu", submission_id=submission_id
                    ).pack(),
                ),
            ]
        ]
    )


def reject_reasons_keyboard(submission_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for reason in RejectReason:
        builder.button(
            text=REJECT_REASON_TEXTS[reason].capitalize(),
            callback_data=VerdictCB(
                action="reject", submission_id=submission_id, reason=reason.value
            ),
        )
    builder.button(
        text="◀️ Назад",
        callback_data=VerdictCB(action="back", submission_id=submission_id),
    )
    builder.adjust(2)
    return builder.as_markup()
