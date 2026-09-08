"""Несколько групп: у каждой свой челлендж, тренировки и судьи

Раньше «где принимаем кружки», «куда постить тренировки» и «кто судья»
жили в .env одним набором значений — бот обслуживал ровно одну группу.
Теперь это строка в clubs, а челленджи и тренировки к ней привязаны.

Данные не теряются: из текущего .env собирается первый клуб, и всё
существующее (челленджи, тренировки) переезжает к нему. Значения берутся
не из кода, а из окружения — иначе миграция врала бы про чужую установку.

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-02
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bot.config import get_settings

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "clubs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("participants_thread_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("trainings_thread_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("checkins_thread_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("judges_chat_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("judge_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("admin_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(op.f("ix_clubs_chat_id"), "clubs", ["chat_id"], unique=True)
    op.create_index(op.f("ix_clubs_is_active"), "clubs", ["is_active"])

    with op.batch_alter_table("challenges") as batch:
        batch.add_column(sa.Column("club_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_challenges_club_id"), "challenges", ["club_id"])

    with op.batch_alter_table("trainings") as batch:
        batch.add_column(sa.Column("club_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_trainings_club_id"), "trainings", ["club_id"])

    # Через get_settings, а не os.getenv: .env читает pydantic, и в окружении
    # процесса этих переменных может просто не быть.
    settings = get_settings()
    chat_id = settings.participants_chat_id
    if not chat_id:
        # Свежая установка без .env — клуб заведут командой /newclub.
        return

    op.execute(
        sa.text(
            "INSERT INTO clubs (title, chat_id, participants_thread_id,"
            " trainings_thread_id, checkins_thread_id, judges_chat_id,"
            " judge_ids, admin_ids, is_active, created_at)"
            " VALUES (:title, :chat, :pt, :tt, :ct, :jc, :ji, :ai, 1, CURRENT_TIMESTAMP)"
        ).bindparams(
            title=settings.club_name,
            chat=chat_id,
            pt=settings.participants_thread_id,
            tt=settings.trainings_thread_id,
            ct=settings.checkins_thread_id,
            jc=settings.judges_chat_id,
            ji=json.dumps(list(settings.judge_ids)),
            ai=json.dumps(list(settings.admin_ids)),
        )
    )
    op.execute("UPDATE challenges SET club_id = (SELECT id FROM clubs LIMIT 1)")
    op.execute("UPDATE trainings SET club_id = (SELECT id FROM clubs LIMIT 1)")


def downgrade() -> None:
    op.drop_index(op.f("ix_trainings_club_id"), table_name="trainings")
    with op.batch_alter_table("trainings") as batch:
        batch.drop_column("club_id")
    op.drop_index(op.f("ix_challenges_club_id"), table_name="challenges")
    with op.batch_alter_table("challenges") as batch:
        batch.drop_column("club_id")
    op.drop_index(op.f("ix_clubs_is_active"), table_name="clubs")
    op.drop_index(op.f("ix_clubs_chat_id"), table_name="clubs")
    op.drop_table("clubs")
