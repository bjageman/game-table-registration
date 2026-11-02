"""Track Discord messages removed during event cleanup."""

import sqlalchemy as sa
from alembic import op

revision = "20261101_discord_cleanup"
down_revision = "20261101_reaction_signups"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("events", sa.Column("signup_deleted_at", sa.Float(), nullable=True))
    op.add_column("announcements", sa.Column("deleted_at", sa.Float(), nullable=True))


def downgrade():
    op.drop_column("announcements", "deleted_at")
    op.drop_column("events", "signup_deleted_at")
