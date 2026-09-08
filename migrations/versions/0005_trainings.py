"""Тренировки бегового клуба

Отдельной таблицы шаблонов нет: «повторить» берёт последнюю подходящую
тренировку из этой же таблицы — история и есть шаблон.

Напоминания хранятся списком отправленных часов, а не парой булевых полей:
расписание напоминаний настраивается в .env и меняется без миграции.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trainings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("training_type", sa.String(length=64), nullable=False),
        sa.Column("location", sa.String(length=256), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("start_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "draft", "published", "cancelled",
                name="training_status", native_enum=False, length=32,
            ),
            nullable=False,
        ),
        sa.Column("chat_id", sa.BigInteger(), nullable=True),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("reminders_enabled", sa.Boolean(), nullable=False),
        sa.Column("reminders_sent", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"],
            name=op.f("fk_trainings_created_by_users"), ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trainings")),
    )
    op.create_index(op.f("ix_trainings_start_at"), "trainings", ["start_at"])
    op.create_index(op.f("ix_trainings_status"), "trainings", ["status"])
    op.create_index("ix_trainings_start_status", "trainings", ["start_at", "status"])
    op.create_index("ix_trainings_type", "trainings", ["training_type"])

    op.create_table(
        "training_participants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("training_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "going", "maybe", "not_going",
                name="rsvp_status", native_enum=False, length=32,
            ),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["training_id"], ["trainings.id"],
            name=op.f("fk_training_participants_training_id_trainings"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name=op.f("fk_training_participants_user_id_users"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_training_participants")),
        # Один человек — один актуальный ответ на тренировку.
        sa.UniqueConstraint("training_id", "user_id", name="uq_training_participant"),
    )
    op.create_index(
        op.f("ix_training_participants_training_id"), "training_participants", ["training_id"]
    )
    op.create_index(
        op.f("ix_training_participants_user_id"), "training_participants", ["user_id"]
    )


def downgrade() -> None:
    op.drop_table("training_participants")
    op.drop_table("trainings")
