from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0002_profile_verifications"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}


def upgrade() -> None:
    op.create_table(
        "auth_profile_verifications",
        sa.Column("id", sa.BINARY(16), nullable=False),
        sa.Column("auth_profile_id", sa.BINARY(16), nullable=False),
        sa.Column("status", mysql.VARCHAR(20), nullable=False),
        sa.Column("worker_id", mysql.VARCHAR(100)),
        sa.Column("process_pid", mysql.INTEGER),
        sa.Column("process_group_id", mysql.INTEGER),
        sa.Column("requested_at", mysql.DATETIME(fsp=3), nullable=False),
        sa.Column("started_at", mysql.DATETIME(fsp=3)),
        sa.Column("heartbeat_at", mysql.DATETIME(fsp=3)),
        sa.Column("finished_at", mysql.DATETIME(fsp=3)),
        sa.Column("error_code", mysql.VARCHAR(100)),
        sa.Column("error_message", mysql.TEXT),
        sa.ForeignKeyConstraint(
            ["auth_profile_id"],
            ["auth_profiles.id"],
            name="fk_profile_verifications_profile",
        ),
        sa.PrimaryKeyConstraint("id"),
        **TABLE_OPTIONS,
    )
    op.create_index(
        "ix_profile_verifications_claim",
        "auth_profile_verifications",
        ["status", "requested_at"],
    )
    op.create_index(
        "ix_profile_verifications_profile",
        "auth_profile_verifications",
        ["auth_profile_id", "requested_at"],
    )


def downgrade() -> None:
    op.drop_table("auth_profile_verifications")
