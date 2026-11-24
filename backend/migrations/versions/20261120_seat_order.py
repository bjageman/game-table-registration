"""Preserve seated player positions independently of the saved lottery draw."""

import sqlalchemy as sa
from alembic import op

revision = "20261120_seat_order"
down_revision = "20261119_player_swaps"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "lottery_runs",
        sa.Column(
            "seat_order",
            sa.JSON(),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade():
    op.drop_column("lottery_runs", "seat_order")
