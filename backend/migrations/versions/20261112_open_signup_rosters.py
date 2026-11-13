"""Add optional live Discord signup rosters and durable refresh state."""

import sqlalchemy as sa
from alembic import op

revision = "20261112_open_signup_rosters"
down_revision = "20261112_general_timezone"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "assignment_preferences",
        sa.Column(
            "show_open_signup_players",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "events", sa.Column("signup_roster_hash", sa.String(64), nullable=True)
    )
    op.add_column(
        "events", sa.Column("signup_roster_checked_at", sa.Float(), nullable=True)
    )
    op.add_column(
        "events", sa.Column("signup_roster_messages", sa.JSON(), nullable=True)
    )
    # Existing open posts were created with the newer embed layout while the
    # roster option was not yet available. Queue them to be restored to the
    # original plain-message format unless their owner enables rosters.
    op.execute(
        "UPDATE events SET signup_roster_hash = 'restore' "
        "WHERE status = 'open' AND message_id IS NOT NULL"
    )


def downgrade():
    op.drop_column("events", "signup_roster_messages")
    op.drop_column("events", "signup_roster_checked_at")
    op.drop_column("events", "signup_roster_hash")
    op.drop_column("assignment_preferences", "show_open_signup_players")
