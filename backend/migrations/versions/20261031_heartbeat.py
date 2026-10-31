"""Durable signup-worker heartbeat for missed cutoff detection."""

import sqlalchemy as sa
from alembic import op

revision = "20261031_heartbeat"
down_revision = "20261031_voters"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "worker_heartbeats",
        sa.Column("name", sa.String(100), primary_key=True),
        sa.Column("last_seen", sa.Float(), nullable=False),
    )


def downgrade():
    op.drop_table("worker_heartbeats")
