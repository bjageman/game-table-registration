"""Durable assignment announcement queue."""

import sqlalchemy as sa
from alembic import op

revision = "20261101_announcements"
down_revision = "20261031_assignments"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "announcements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "event_id", sa.String(36), sa.ForeignKey("events.id"), nullable=False
        ),
        sa.Column("part", sa.Integer(), nullable=False),
        sa.Column("channel_id", sa.String(32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("next_attempt", sa.Float(), nullable=False),
        sa.Column("attempted_at", sa.Float(), nullable=True),
        sa.Column("unknown", sa.Boolean(), nullable=False),
        sa.Column("token", sa.String(64), nullable=True),
        sa.Column("lease_until", sa.Float(), nullable=True),
        sa.Column("message_id", sa.String(32), nullable=True),
        sa.Column("error", sa.String(500), nullable=True),
        sa.UniqueConstraint("event_id", "part"),
    )

    op.create_index("ix_announcement_due", "announcements", ["state", "next_attempt"])


def downgrade():
    op.drop_table("announcements")
