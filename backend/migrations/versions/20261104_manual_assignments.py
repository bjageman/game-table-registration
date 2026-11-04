"""Track manager additions from assignment waitlists."""

import sqlalchemy as sa
from alembic import op

revision = "20261104_manual_assignments"
down_revision = "20261104_event_description"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "event_manual_assignments",
        sa.Column(
            "event_id",
            sa.String(36),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("discord_id", sa.String(32), primary_key=True),
        sa.Column("table_name", sa.String(35), nullable=False),
        sa.Column("assigned_at", sa.Float(), nullable=False),
    )


def downgrade():
    op.drop_table("event_manual_assignments")
