"""Пост тренировки: погода, план, экипировка, ссылка, заметки

Реальный пост клуба состоит не из «типа и описания», а из блоков: погода,
план по пунктам, что взять, локация со ссылкой на 2ГИС и приписки вроде
платного входа. Всё это переносится «повтором» как есть — от недели к неделе
меняются только дата и погода.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = (
    ("location_url", sa.String(length=512)),
    ("weather", sa.String(length=256)),
    ("plan", sa.Text()),
    ("gear", sa.Text()),
    ("notes", sa.Text()),
)


def upgrade() -> None:
    with op.batch_alter_table("trainings") as batch:
        for name, kind in _COLUMNS:
            batch.add_column(sa.Column(name, kind, nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("trainings") as batch:
        for name, _ in reversed(_COLUMNS):
            batch.drop_column(name)
