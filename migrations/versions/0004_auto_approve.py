"""Кружок зачитывается сразу, судья отменяет

Было: сдача ждёт судью в pending, участник до вердикта заблокирован.
Стало: кружок, прошедший автопроверки, сразу approved — день закрыт, серия
растёт. Судья либо подтверждает, либо отменяет зачёт.

Поэтому:
* reviewed_at / reviewed_by — очередь судей строится по непросмотренным,
  а не по незачтённым;
* новый статус revoked — отмена уже после закрытия дня: кружок уходит из
  месячного счёта, но день остаётся закрытым и серия не рвётся задним числом.

Старые pending-записи не трогаем: они доживут своим ходом.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    # Статус хранится строкой без CHECK-констрейнта (SQLAlchemy 2.x не создаёт
    # его для native_enum=False), поэтому новое значение схему не ломает.
    with op.batch_alter_table("submissions") as batch:
        batch.add_column(sa.Column("reviewed_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("reviewed_by", sa.BigInteger(), nullable=True))

    op.create_index("ix_submissions_reviewed", "submissions", ["reviewed_at", "status"])


def downgrade() -> None:
    op.drop_index("ix_submissions_reviewed", table_name="submissions")
    op.execute("UPDATE submissions SET status = 'rejected' WHERE status = 'revoked'")
    with op.batch_alter_table("submissions") as batch:
        batch.drop_column("reviewed_by")
        batch.drop_column("reviewed_at")
