"""Explicit signup windows and timezone."""

import sqlalchemy as sa
from alembic import op

revision = "20261031_times"
down_revision = "5f0893d925a1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "events",
        sa.Column("timezone", sa.String(100), nullable=False, server_default="UTC"),
    )
    op.add_column("events", sa.Column("opens_at", sa.Float(), nullable=True))
    op.add_column("events", sa.Column("signup_closes_at", sa.Float(), nullable=True))


def downgrade():
    op.drop_column("events", "signup_closes_at")
    op.drop_column("events", "opens_at")
    op.drop_column("events", "timezone")
