"""Bind Discord connection OAuth states to their initiating account."""

import sqlalchemy as sa
from alembic import op

revision = "20261101_connect_callback"
down_revision = "20261101_disconnect"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "login_states",
        sa.Column("purpose", sa.String(16), nullable=False, server_default="login"),
    )
    op.add_column("login_states", sa.Column("user_id", sa.String(32), nullable=True))


def downgrade():
    op.drop_column("login_states", "user_id")
    op.drop_column("login_states", "purpose")
