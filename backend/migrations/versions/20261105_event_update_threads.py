"""Add event update threads and durable RSVP thread membership."""

import sqlalchemy as sa
from alembic import op

revision = "20261105_event_update_threads"
down_revision = "20261105_weight_scale_five"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "assignment_preferences",
        sa.Column(
            "post_discord_updates_to_thread",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column("events", sa.Column("update_thread_id", sa.String(32), nullable=True))
    op.add_column("events", sa.Column("thread_sync_at", sa.Float(), nullable=True))
    op.create_table(
        "event_thread_members",
        sa.Column(
            "event_id",
            sa.String(36),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("discord_id", sa.String(32), primary_key=True),
        sa.Column("added_at", sa.Float(), nullable=True),
    )


def downgrade():
    op.drop_table("event_thread_members")
    op.drop_column("events", "thread_sync_at")
    op.drop_column("events", "update_thread_id")
    op.drop_column("assignment_preferences", "post_discord_updates_to_thread")
