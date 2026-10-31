"""Durable operation tracking."""

import sqlalchemy as sa
from alembic import op

revision = "20261031_worker"
down_revision = "20261031_times"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "events", sa.Column("operation_started_at", sa.Float(), nullable=True)
    )
    op.add_column("events", sa.Column("last_error", sa.String(500), nullable=True))


def downgrade():
    op.drop_column("events", "last_error")
    op.drop_column("events", "operation_started_at")
