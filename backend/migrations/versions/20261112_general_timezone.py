"""Add the organization/personal timezone preference."""

import sqlalchemy as sa
from alembic import op

revision = "20261112_general_timezone"
down_revision = "20261105_event_update_threads"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "assignment_preferences", sa.Column("timezone", sa.String(64), nullable=True)
    )


def downgrade():
    op.drop_column("assignment_preferences", "timezone")
