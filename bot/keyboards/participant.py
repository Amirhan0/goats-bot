from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

JOIN_CB = "join"
WIPE_YES_CB = "wipe:yes"
WIPE_NO_CB = "wipe:no"


def join_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🚀 Участвовать", callback_data=JOIN_CB)]]
    )


def leave_keyboard(owner_id: int) -> InlineKeyboardMarkup:
    """Именные кнопки: в общей беседе чужой «Да» не должен ничего менять."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Да", callback_data=f"leave:yes:{owner_id}"),
                InlineKeyboardButton(text="Нет", callback_data=f"leave:no:{owner_id}"),
            ]
        ]
    )


def parse_leave_cb(data: str) -> tuple[str, int | None]:
    parts = data.split(":")
    if len(parts) != 3 or not parts[2].lstrip("-").isdigit():
        return "", None
    return parts[1], int(parts[2])


def wipe_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Да", callback_data=WIPE_YES_CB),
                InlineKeyboardButton(text="Нет", callback_data=WIPE_NO_CB),
            ]
        ]
    )
