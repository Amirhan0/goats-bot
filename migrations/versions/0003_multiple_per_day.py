"""Несколько зачтённых кружков в день

Правила поменялись: минимум один кружок в день обязателен (иначе пропуск и
обрыв серии), но сверх минимума можно сдавать сколько угодно — победитель
месяца определяется по общему числу зачтённых кружков.

Партиальный уникальный индекс «один зачёт на (участие, день)» этому прямо
противоречит и снимается. Серии по-прежнему считаются по РАЗЛИЧНЫМ дням,
так что второй кружок за день серию не удлиняет.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_submission_approved_per_day")
    # Выборки топа за месяц идут по day_date + status.
    op.create_index(
        "ix_submissions_date_status", "submissions", ["day_date", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_submissions_date_status", table_name="submissions")
    # Откат возможен только если лишние зачёты за день уже вычищены вручную.
    op.execute(
        "CREATE UNIQUE INDEX uq_submission_approved_per_day "
        "ON submissions (participation_id, challenge_day) "
        "WHERE status = 'approved'"
    )
