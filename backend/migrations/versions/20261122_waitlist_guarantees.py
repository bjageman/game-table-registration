"""Optional next-event guarantees for waitlisted players."""

import sqlalchemy as sa
from alembic import op

revision = "20261122_waitlist_guarantees"
down_revision = "20261121_assignment_dms"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "assignment_preferences",
        sa.Column(
            "guarantee_waitlisted_players",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "assignment_preferences",
        sa.Column(
            "waitlist_guarantee_retention_hours",
            sa.Integer(),
            nullable=False,
            server_default="5",
        ),
    )


def downgrade():
    op.drop_column("assignment_preferences", "waitlist_guarantee_retention_hours")
    op.drop_column("assignment_preferences", "guarantee_waitlisted_players")
