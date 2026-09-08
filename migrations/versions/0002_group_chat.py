"""Приём кружков переехал из лички в общую беседу

Кружок теперь лежит в беседе, а не в личке бота, поэтому у сдачи появился
chat_id. Публикация в отдельный канал больше не нужна: кружок уже на виду,
бот просто помечает его реплаем с вердиктом — его id и храним.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("submissions") as batch:
        batch.add_column(
            sa.Column("chat_id", sa.BigInteger(), nullable=False, server_default="0")
        )
        batch.add_column(sa.Column("verdict_message_id", sa.BigInteger(), nullable=True))
        batch.drop_column("channel_message_id")
        batch.drop_column("channel_caption_message_id")


def downgrade() -> None:
    with op.batch_alter_table("submissions") as batch:
        batch.add_column(sa.Column("channel_message_id", sa.BigInteger(), nullable=True))
        batch.add_column(
            sa.Column("channel_caption_message_id", sa.BigInteger(), nullable=True)
        )
        batch.drop_column("verdict_message_id")
        batch.drop_column("chat_id")
