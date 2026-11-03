"""Remember explicit disconnections instead of restoring legacy defaults."""

import sqlalchemy as sa
from alembic import op

revision = "20261101_disconnect"
down_revision = "20261101_weight_adjustments"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "user_settings",
        sa.Column(
            "disconnected", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade():
    op.drop_column("user_settings", "disconnected")
