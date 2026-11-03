"""Persistent synthetic signups and their isolated player profiles."""

import sqlalchemy as sa
from alembic import op

revision = "20261101_test_users"
down_revision = "20261101_announcements"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("events", sa.Column("test_signups", sa.JSON(), nullable=True))
    op.add_column(
        "player_profiles",
        sa.Column("is_test", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_column("player_profiles", "is_test")
    op.drop_column("events", "test_signups")
