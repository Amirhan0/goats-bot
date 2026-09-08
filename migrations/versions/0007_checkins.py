"""Приходы на тренировку по скриншоту Стравы

Скриншот прилетает реплаем на пост тренировки, судья подтверждает или
отклоняет. Один приход на человека на тренировку — гарантия на уровне
уникального индекса, а не на уровне «мы аккуратно проверяем в коде».

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "training_checkins",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("training_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("file_id", sa.String(length=256), nullable=False),
        sa.Column("file_unique_id", sa.String(length=128), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "approved", "rejected",
                name="checkin_status", native_enum=False, length=32,
            ),
            nullable=False,
        ),
        sa.Column("judge_id", sa.Integer(), nullable=True),
        sa.Column("judged_at", sa.DateTime(), nullable=True),
        sa.Column("reject_reason", sa.String(length=256), nullable=True),
        sa.Column("judge_message_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["training_id"], ["trainings.id"],
            name=op.f("fk_training_checkins_training_id_trainings"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name=op.f("fk_training_checkins_user_id_users"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["judge_id"], ["users.id"],
            name=op.f("fk_training_checkins_judge_id_users"), ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_training_checkins")),
        sa.UniqueConstraint("training_id", "user_id", name="uq_training_checkin"),
    )
    op.create_index(
        op.f("ix_training_checkins_training_id"), "training_checkins", ["training_id"]
    )
    op.create_index(op.f("ix_training_checkins_user_id"), "training_checkins", ["user_id"])
    op.create_index(op.f("ix_training_checkins_status"), "training_checkins", ["status"])
    op.create_index("ix_checkins_status", "training_checkins", ["status"])


def downgrade() -> None:
    op.drop_table("training_checkins")
