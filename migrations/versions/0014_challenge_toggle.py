"""Выключатель челленджа у клуба

Челлендж с кружками можно поставить на паузу, не трогая тренировки:
бот перестаёт принимать кружки и постить про них, данные остаются.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("clubs") as batch:
        batch.add_column(
            sa.Column("challenge_enabled", sa.Boolean(), nullable=False, server_default=sa.true())
        )


def downgrade() -> None:
    with op.batch_alter_table("clubs") as batch:
        batch.drop_column("challenge_enabled")
