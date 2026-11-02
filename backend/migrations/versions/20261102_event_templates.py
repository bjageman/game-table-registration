"""Save reusable event details per user."""

import sqlalchemy as sa
from alembic import op

revision = "20261102_event_templates"
down_revision = "20261101_discord_cleanup"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "event_templates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("duration_hours", sa.Integer(), nullable=False),
        sa.Column("tables", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
    )
    op.create_index("ix_event_templates_user_id", "event_templates", ["user_id"])


def downgrade():
    op.drop_index("ix_event_templates_user_id", table_name="event_templates")
    op.drop_table("event_templates")
