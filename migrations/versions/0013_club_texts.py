"""Задание и призы — свои у каждого клуба

Тексты правил собирались из общих значений, и в новой группе показывались
призы GOATS: чужие обещания чужим людям. Теперь задание и призы лежат
на клубе, а пустое значение означает «взять общее из .env» (для задания)
или «не показывать блок вовсе» (для призов).

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bot import texts
from bot.config import get_settings

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("clubs") as batch:
        batch.add_column(
            sa.Column("challenge_task", sa.Text(), nullable=False, server_default="")
        )
        batch.add_column(sa.Column("prizes", sa.Text(), nullable=False, server_default=""))

    # Призы, которые уже объявлены людям, остаются у своего клуба.
    settings = get_settings()
    if settings.participants_chat_id:
        op.execute(
            sa.text("UPDATE clubs SET prizes = :p WHERE chat_id = :chat").bindparams(
                p=texts.PRIZES, chat=settings.participants_chat_id
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("clubs") as batch:
        batch.drop_column("prizes")
        batch.drop_column("challenge_task")
