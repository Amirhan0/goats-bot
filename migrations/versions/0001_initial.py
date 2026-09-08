"""Начальная схема

Revision ID: 0001
Revises:
Create Date: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("first_name", sa.String(length=128), nullable=False),
        sa.Column(
            "role",
            sa.Enum("participant", "judge", "admin", name="role", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("joined_at", sa.DateTime(), nullable=False),
        sa.Column("is_blocked", sa.Boolean(), nullable=False),
        sa.Column("block_reason", sa.String(length=256), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    # unique=True + index=True в модели даёт один уникальный индекс, а не
    # отдельный UNIQUE-констрейнт — иначе `alembic check` видит расхождение.
    op.create_index(op.f("ix_users_telegram_id"), "users", ["telegram_id"], unique=True)

    op.create_table(
        "challenges",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("rules_text", sa.Text(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("min_duration_sec", sa.Integer(), nullable=False),
        sa.Column("max_duration_sec", sa.Integer(), nullable=False),
        sa.Column("is_test", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_challenges")),
    )
    op.create_index(op.f("ix_challenges_is_test"), "challenges", ["is_test"])
    op.create_index(op.f("ix_challenges_is_active"), "challenges", ["is_active"])

    op.create_table(
        "participations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("challenge_id", sa.Integer(), nullable=False),
        sa.Column("joined_at", sa.DateTime(), nullable=False),
        sa.Column("join_day", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "active", "dropped", name="participation_status", native_enum=False, length=32
            ),
            nullable=False,
        ),
        sa.Column("left_at", sa.DateTime(), nullable=True),
        sa.Column("current_streak", sa.Integer(), nullable=False),
        sa.Column("best_streak", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["challenge_id"],
            ["challenges.id"],
            name=op.f("fk_participations_challenge_id_challenges"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_participations_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_participations")),
        sa.UniqueConstraint("user_id", "challenge_id", name="uq_participation"),
    )
    op.create_index(op.f("ix_participations_user_id"), "participations", ["user_id"])
    op.create_index(op.f("ix_participations_challenge_id"), "participations", ["challenge_id"])
    op.create_index(op.f("ix_participations_status"), "participations", ["status"])

    op.create_table(
        "submissions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("participation_id", sa.Integer(), nullable=False),
        sa.Column("challenge_day", sa.Integer(), nullable=False),
        sa.Column("day_date", sa.Date(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("file_id", sa.String(length=256), nullable=False),
        sa.Column("file_unique_id", sa.String(length=128), nullable=False),
        sa.Column("duration", sa.Integer(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "approved",
                "rejected",
                name="submission_status",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("reject_reason", sa.String(length=256), nullable=True),
        sa.Column("judge_id", sa.Integer(), nullable=True),
        sa.Column("judged_at", sa.DateTime(), nullable=True),
        sa.Column("judge_message_id", sa.BigInteger(), nullable=True),
        sa.Column("judge_video_message_id", sa.BigInteger(), nullable=True),
        sa.Column("channel_message_id", sa.BigInteger(), nullable=True),
        sa.Column("channel_caption_message_id", sa.BigInteger(), nullable=True),
        sa.Column("anti_cheat_flags", sa.JSON(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("undone_at", sa.DateTime(), nullable=True),
        sa.Column("undone_by", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(
            ["judge_id"],
            ["users.id"],
            name=op.f("fk_submissions_judge_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["participation_id"],
            ["participations.id"],
            name=op.f("fk_submissions_participation_id_participations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_submissions")),
        sa.UniqueConstraint("file_unique_id", name="uq_submissions_file_unique_id"),
        sa.UniqueConstraint(
            "participation_id", "challenge_day", "attempt_no", name="uq_submission_attempt"
        ),
    )
    op.create_index(op.f("ix_submissions_participation_id"), "submissions", ["participation_id"])
    op.create_index(op.f("ix_submissions_day_date"), "submissions", ["day_date"])
    op.create_index(op.f("ix_submissions_status"), "submissions", ["status"])
    op.create_index("ix_submissions_day_status", "submissions", ["challenge_day", "status"])
    op.create_index("ix_submissions_part_day", "submissions", ["participation_id", "challenge_day"])
    op.create_index("ix_submissions_judge_message", "submissions", ["judge_message_id"])

    # Ключевое ограничение: не больше одного зачёта на (участие, день).
    # Партиальный индекс — pending/rejected попыток может быть сколько угодно.
    op.execute(
        "CREATE UNIQUE INDEX uq_submission_approved_per_day "
        "ON submissions (participation_id, challenge_day) "
        "WHERE status = 'approved'"
    )

    op.create_table(
        "daily_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("challenge_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("is_manual", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["challenge_id"],
            ["challenges.id"],
            name=op.f("fk_daily_codes_challenge_id_challenges"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_daily_codes")),
        sa.UniqueConstraint("challenge_id", "date", name="uq_daily_code"),
    )
    op.create_index(op.f("ix_daily_codes_challenge_id"), "daily_codes", ["challenge_id"])
    op.create_index(op.f("ix_daily_codes_date"), "daily_codes", ["date"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.BigInteger(), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=True),
        sa.Column("target_id", sa.BigInteger(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_index(op.f("ix_audit_log_actor_id"), "audit_log", ["actor_id"])
    op.create_index(op.f("ix_audit_log_action"), "audit_log", ["action"])
    op.create_index(op.f("ix_audit_log_created_at"), "audit_log", ["created_at"])
    op.create_index("ix_audit_created", "audit_log", ["created_at"])


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("daily_codes")
    op.execute("DROP INDEX IF EXISTS uq_submission_approved_per_day")
    op.drop_table("submissions")
    op.drop_table("participations")
    op.drop_table("challenges")
    op.drop_table("users")
