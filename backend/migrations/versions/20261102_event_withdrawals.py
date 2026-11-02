"""Track post-assignment withdrawals and promotion notices."""

import sqlalchemy as sa
from alembic import op

revision = "20261102_event_withdrawals"
down_revision = "20261102_event_player_settings"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "announcements",
        sa.Column("kind", sa.String(16), nullable=False, server_default="assignment"),
    )
    op.create_table(
        "event_withdrawals",
        sa.Column(
            "event_id",
            sa.String(36),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("discord_id", sa.String(32), primary_key=True),
        sa.Column("table_name", sa.String(35), nullable=False),
        sa.Column("withdrawn_at", sa.Float(), nullable=False),
        sa.Column("promoted_id", sa.String(32), nullable=True),
    )


def downgrade():
    op.drop_table("event_withdrawals")
    op.drop_column("announcements", "kind")
