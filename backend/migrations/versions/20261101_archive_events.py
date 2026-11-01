"""Preserve assigned events while archiving them from the active list."""

import sqlalchemy as sa
from alembic import op

revision = "20261101_archive_events"
down_revision = "20261101_selected_guarantees"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("events", sa.Column("archived_at", sa.Float(), nullable=True))


def downgrade():
    op.drop_column("events", "archived_at")
