"""Assignment PM controls and scoped player notification opt-outs."""

import sqlalchemy as sa
from alembic import op

revision = "20261121_assignment_dms"
down_revision = "20261120_seat_order"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "assignment_preferences",
        sa.Column(
            "dm_assignments", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
    )
    op.add_column(
        "player_profiles",
        sa.Column(
            "seat_notifications", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
    )
    op.add_column(
        "promotion_dms",
        sa.Column("kind", sa.String(16), nullable=False, server_default="promotion"),
    )


def downgrade():
    op.drop_column("promotion_dms", "kind")
    op.drop_column("player_profiles", "seat_notifications")
    op.drop_column("assignment_preferences", "dm_assignments")
