"""Track organizer removals independently for each table."""

import sqlalchemy as sa
from alembic import op

revision = "20261116_table_removals"
down_revision = "20261115_recurring_edits"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "event_table_removals",
        sa.Column(
            "event_id",
            sa.String(36),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("discord_id", sa.String(32), primary_key=True),
        sa.Column("table_name", sa.String(35), primary_key=True),
    )


def downgrade():
    op.drop_table("event_table_removals")
