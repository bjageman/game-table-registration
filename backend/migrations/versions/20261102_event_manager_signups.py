"""Store manager additions and removals for event signups."""

import sqlalchemy as sa
from alembic import op

revision = "20261102_event_manager_signups"
down_revision = "20261102_event_withdrawals"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "event_manager_signups",
        sa.Column(
            "event_id",
            sa.String(36),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("discord_id", sa.String(32), primary_key=True),
        sa.Column("discord_name", sa.String(100), nullable=False),
        sa.Column("choices", sa.JSON(), nullable=False),
        sa.Column("removed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_table("event_manager_signups")
