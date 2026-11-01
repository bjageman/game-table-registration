"""Guaranteed seats on persistent player profiles and frozen closing settings."""

import sqlalchemy as sa
from alembic import op

revision = "20261101_guarantees"
down_revision = "20261101_test_users"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "player_profiles",
        sa.Column(
            "guaranteed_seat", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "player_profiles", sa.Column("guaranteed_table", sa.String(35), nullable=True)
    )
    op.add_column("events", sa.Column("close_guarantees", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("events", "close_guarantees")
    op.drop_column("player_profiles", "guaranteed_table")
    op.drop_column("player_profiles", "guaranteed_seat")
