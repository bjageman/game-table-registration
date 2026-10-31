"""Weekly schedule templates and unique occurrences."""

import sqlalchemy as sa
from alembic import op

revision = "20261031_recur"
down_revision = "20261031_worker"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "schedules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("timezone", sa.String(100), nullable=False),
        sa.Column("rule", sa.JSON(), nullable=False),
        sa.Column("tables", sa.JSON(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=False),
        sa.Column("last_error", sa.String(500), nullable=True),
    )
    op.create_index("ix_schedules_guild_id", "schedules", ["guild_id"])
    op.add_column("events", sa.Column("schedule_id", sa.String(36), nullable=True))
    op.add_column("events", sa.Column("occurrence_date", sa.String(10), nullable=True))
    op.add_column(
        "events",
        sa.Column(
            "overridden", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.create_index(
        "uq_event_occurrence", "events", ["schedule_id", "occurrence_date"], unique=True
    )


def downgrade():
    op.drop_index("uq_event_occurrence", "events")
    op.drop_column("events", "overridden")
    op.drop_column("events", "occurrence_date")
    op.drop_column("events", "schedule_id")
    op.drop_index("ix_schedules_guild_id", "schedules")
    op.drop_table("schedules")
