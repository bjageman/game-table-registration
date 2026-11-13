"""Optional private waitlist promotion notifications with durable delivery."""

import sqlalchemy as sa
from alembic import op

revision = "20261113_promotion_dms"
down_revision = "20261113_repair_open_roster_schema"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "assignment_preferences",
        sa.Column(
            "dm_waitlist_promotions",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_table(
        "promotion_dms",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "event_id",
            sa.String(36),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("discord_id", sa.String(32), nullable=False),
        sa.Column("table_name", sa.String(35), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("next_attempt", sa.Float(), nullable=False),
        sa.Column("attempted_at", sa.Float(), nullable=True),
        sa.Column("unknown", sa.Boolean(), nullable=False),
        sa.Column("token", sa.String(64), nullable=True),
        sa.Column("lease_until", sa.Float(), nullable=True),
        sa.Column("channel_id", sa.String(32), nullable=True),
        sa.Column("message_id", sa.String(32), nullable=True),
        sa.Column("error", sa.String(500), nullable=True),
        sa.UniqueConstraint("event_id", "discord_id"),
    )
    op.create_index("ix_promotion_dm_due", "promotion_dms", ["state", "next_attempt"])


def downgrade():
    op.drop_index("ix_promotion_dm_due", table_name="promotion_dms")
    op.drop_table("promotion_dms")
    op.drop_column("assignment_preferences", "dm_waitlist_promotions")
