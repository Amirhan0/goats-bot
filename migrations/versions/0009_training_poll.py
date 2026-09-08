"""Сбор участников через неанонимный опрос Telegram

Инлайн-кнопки показывали только счётчик. Неанонимный опрос показывает
поимённо, кто как ответил, — и при этом бот получает poll_answer, поэтому
своя таблица участников остаётся в синхроне и напоминания работают.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("trainings") as batch:
        batch.add_column(sa.Column("poll_message_id", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("poll_id", sa.String(length=64), nullable=True))
    op.create_index(op.f("ix_trainings_poll_id"), "trainings", ["poll_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_trainings_poll_id"), table_name="trainings")
    with op.batch_alter_table("trainings") as batch:
        batch.drop_column("poll_id")
        batch.drop_column("poll_message_id")
