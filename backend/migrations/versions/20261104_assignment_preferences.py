"""Scope assignment preferences to organizations or personal events."""

import sqlalchemy as sa
from alembic import op

revision = "20261104_assignment_preferences"
down_revision = "20261104_merge_location_manual"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "assignment_preferences",
        sa.Column("scope_key", sa.String(64), primary_key=True),
        sa.Column(
            "automatic_weight_adjustment",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "announce_table_changes",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade():
    op.drop_table("assignment_preferences")
