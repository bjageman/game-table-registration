"""Persist organizer additions without changing the original lottery draw."""

import sqlalchemy as sa
from alembic import op

revision = "20261113_waitlist_additions"
down_revision = "20261113_promotion_dms"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "event_waitlist_additions",
        sa.Column(
            "event_id",
            sa.String(36),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("discord_id", sa.String(32), primary_key=True),
        sa.Column("table_name", sa.String(35), primary_key=True),
        sa.Column("discord_name", sa.String(100), nullable=False),
        sa.Column("added_at", sa.Float(), nullable=False),
    )


def downgrade():
    op.drop_table("event_waitlist_additions")
