"""Внешние ключи challenges.club_id и trainings.club_id → clubs.id

В 0011 колонки добавлены, а constraint — нет: SQLite не умеет ALTER TABLE
ADD CONSTRAINT, и его приходится ставить пересборкой таблицы. Без него
`alembic check` расходится с моделями, а удаление клуба оставляло бы
висячие челленджи вместо каскада.

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-02
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # recreate="always": иначе batch попробует обойтись ALTER-ом и упадёт.
    with op.batch_alter_table("challenges", recreate="always") as batch:
        batch.create_foreign_key(
            "fk_challenges_club_id_clubs", "clubs", ["club_id"], ["id"], ondelete="CASCADE"
        )
    with op.batch_alter_table("trainings", recreate="always") as batch:
        batch.create_foreign_key(
            "fk_trainings_club_id_clubs", "clubs", ["club_id"], ["id"], ondelete="CASCADE"
        )


def downgrade() -> None:
    with op.batch_alter_table("trainings", recreate="always") as batch:
        batch.drop_constraint("fk_trainings_club_id_clubs", type_="foreignkey")
    with op.batch_alter_table("challenges", recreate="always") as batch:
        batch.drop_constraint("fk_challenges_club_id_clubs", type_="foreignkey")
