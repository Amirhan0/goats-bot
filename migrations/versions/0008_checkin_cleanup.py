"""Уборка скриншотов из ветки тренировки

Через сутки после тренировки скриншоты и ответы бота удаляются, чтобы
ветка не забивалась. Пост тренировки остаётся — по нему видно историю.

Чтобы было что удалять, запоминаем id ответов бота; cleaned_at не даёт
повторно ломиться в уже удалённые сообщения.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("training_checkins") as batch:
        batch.add_column(
            sa.Column("bot_message_ids", sa.JSON(), nullable=False, server_default="[]")
        )
        batch.add_column(sa.Column("cleaned_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("training_checkins") as batch:
        batch.drop_column("cleaned_at")
        batch.drop_column("bot_message_ids")
