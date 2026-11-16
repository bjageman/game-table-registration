"""Event waitlist controls and placement order independent of the saved draw."""

import sqlalchemy as sa
from alembic import op

revision = "20261119_player_swaps"
down_revision = "20261118_event_created_at"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "events",
        sa.Column(
            "auto_promote_waitlist",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "lottery_runs",
        sa.Column(
            "waitlist_order",
            sa.JSON(),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade():
    op.drop_column("lottery_runs", "waitlist_order")
    op.drop_column("events", "auto_promote_waitlist")
