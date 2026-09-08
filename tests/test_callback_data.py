"""Кнопки судьи: упакованное должно распаковываться обратно.

Регрессия из боя: `reason: str` ломал unpack пустого хвостового поля на
aiogram 3.15 — фильтр молча не совпадал, и кнопки не работали вообще.
"""

from __future__ import annotations

import pytest

from bot.db.enums import RejectReason
from bot.keyboards.judge import VerdictCB, reject_reasons_keyboard, verdict_keyboard


@pytest.mark.parametrize("action", ["approve", "reject_menu", "back"])
def test_roundtrip_without_reason(action: str) -> None:
    packed = VerdictCB(action=action, submission_id=42).pack()
    restored = VerdictCB.unpack(packed)

    assert (restored.action, restored.submission_id) == (action, 42)
    assert not restored.reason


def test_roundtrip_with_reason() -> None:
    packed = VerdictCB(
        action="reject", submission_id=7, reason=RejectReason.NO_CODE_WORD.value
    ).pack()
    restored = VerdictCB.unpack(packed)

    assert restored.action == "reject"
    assert restored.reason == RejectReason.NO_CODE_WORD.value


def test_every_button_unpacks() -> None:
    """Проверяем реальные клавиатуры, а не только конструктор."""
    markups = [verdict_keyboard(1), reject_reasons_keyboard(1)]
    buttons = [b for m in markups for row in m.inline_keyboard for b in row]

    assert buttons
    for button in buttons:
        restored = VerdictCB.unpack(button.callback_data)
        assert restored.submission_id == 1
        assert len(button.callback_data.encode()) <= 64  # лимит Telegram
