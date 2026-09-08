"""Топик отчёта у прихода + авто-зачёт приходов

Отчёты переехали в отдельный топик «Приходы», поэтому у прихода появилась
своя ветка: без неё ответ судьи в форуме уходит в General.

Заодно приходы переведены на авто-зачёт, как кружки. Старые pending-записи
досуживать некому — переводим их в approved: они уже висели в очереди,
и отменить любую из них судья может в любой момент.

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("training_checkins") as batch:
        batch.add_column(sa.Column("thread_id", sa.BigInteger(), nullable=True))
    op.execute("UPDATE training_checkins SET status = 'approved' WHERE status = 'pending'")


def downgrade() -> None:
    with op.batch_alter_table("training_checkins") as batch:
        batch.drop_column("thread_id")
