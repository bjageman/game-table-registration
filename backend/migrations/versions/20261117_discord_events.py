"""Optional Discord server events and their end times."""

import sqlalchemy as sa
from alembic import op

revision = "20261117_discord_events"
down_revision = "20261116_table_removals"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "assignment_preferences",
        sa.Column(
            "create_discord_event",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column("events", sa.Column("ends_at", sa.Float(), nullable=True))
    op.add_column(
        "recurring_series", sa.Column("event_length_seconds", sa.Float(), nullable=True)
    )
    op.create_table(
        "discord_scheduled_events",
        sa.Column(
            "event_id",
            sa.String(36),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("discord_id", sa.String(32), nullable=True),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=True),
        sa.Column("checked_at", sa.Float(), nullable=True),
        sa.Column("error", sa.String(500), nullable=True),
    )


def downgrade():
    op.drop_table("discord_scheduled_events")
    op.drop_column("recurring_series", "event_length_seconds")
    op.drop_column("events", "ends_at")
    op.drop_column("assignment_preferences", "create_discord_event")
