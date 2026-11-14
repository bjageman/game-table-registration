"""Record creation times for new events without inventing historical dates."""

import sqlalchemy as sa
from alembic import op

revision = "20261118_event_created_at"
down_revision = "20261117_discord_events"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("events", sa.Column("created_at", sa.Float(), nullable=True))


def downgrade():
    op.drop_column("events", "created_at")
