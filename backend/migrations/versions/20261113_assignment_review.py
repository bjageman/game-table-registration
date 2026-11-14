"""Hold saved assignments for organizer approval before public delivery."""

import sqlalchemy as sa
from alembic import op

revision = "20261113_assignment_review"
down_revision = "20261113_general_defaults"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "assignment_preferences",
        sa.Column(
            "review_assignments_before_discord",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "events", sa.Column("close_review_assignments", sa.Boolean(), nullable=True)
    )


def downgrade():
    op.drop_column("events", "close_review_assignments")
    op.drop_column("assignment_preferences", "review_assignments_before_discord")
