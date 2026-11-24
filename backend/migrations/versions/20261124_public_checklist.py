"""Persist shared public attendance checkmarks with optimistic concurrency."""

import sqlalchemy as sa
from alembic import op

revision = "20261124_public_checklist"
down_revision = "20261123_short_notice"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "events",
        sa.Column("public_checklist", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "events",
        sa.Column(
            "public_checklist_revision",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade():
    op.drop_column("events", "public_checklist_revision")
    op.drop_column("events", "public_checklist")
