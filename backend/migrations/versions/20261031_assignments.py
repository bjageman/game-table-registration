"""Frozen lottery runs and recoverable manual signup closing."""

import sqlalchemy as sa
from alembic import op

revision = "20261031_assignments"
down_revision = "20261031_destinations"
branch_labels = None
depends_on = None


def upgrade():
    for name, kind in [
        ("published_at", sa.Float()),
        ("close_token", sa.String(64)),
        ("close_started_at", sa.Float()),
        ("close_seed", sa.String(64)),
        ("close_weights", sa.JSON()),
        ("close_error", sa.String(500)),
    ]:
        op.add_column("events", sa.Column(name, kind, nullable=True))
    op.execute(
        "UPDATE events SET published_at = closes_at - duration_hours * 3600 "
        "WHERE message_id IS NOT NULL AND closes_at IS NOT NULL"
    )
    op.create_table(
        "lottery_runs",
        sa.Column(
            "event_id", sa.String(36), sa.ForeignKey("events.id"), primary_key=True
        ),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("seed", sa.String(64), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
    )


def downgrade():
    op.drop_table("lottery_runs")
    for name in [
        "close_error",
        "close_weights",
        "close_seed",
        "close_started_at",
        "close_token",
        "published_at",
    ]:
        op.drop_column("events", name)
