"""Store per-event signup weight and table guarantee overrides."""

import sqlalchemy as sa
from alembic import op

revision = "20261102_event_player_settings"
down_revision = "20261102_event_templates"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "event_player_settings",
        sa.Column(
            "event_id",
            sa.String(36),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("discord_id", sa.String(32), primary_key=True),
        sa.Column("weighting", sa.Float(), nullable=True),
        sa.Column("guaranteed_table", sa.String(35), nullable=True),
    )


def downgrade():
    op.drop_table("event_player_settings")
