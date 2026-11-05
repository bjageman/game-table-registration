"""Bind Discord connection attempts to their organization."""

import sqlalchemy as sa
from alembic import op

revision = "20261105_org_connect_state"
down_revision = "20261105_weight_scale_five"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "login_states", sa.Column("organization_id", sa.String(36), nullable=True)
    )


def downgrade():
    op.drop_column("login_states", "organization_id")
