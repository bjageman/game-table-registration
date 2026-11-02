"""Store table selections made through Discord message components."""

import sqlalchemy as sa
from alembic import op

revision = "20261101_custom_signups"
down_revision = "20261101_connect_callback"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "events",
        sa.Column("signup_mode", sa.String(16), nullable=False, server_default="poll"),
    )
    op.create_table(
        "table_signups",
        sa.Column(
            "event_id",
            sa.String(36),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("discord_id", sa.String(32), primary_key=True),
        sa.Column("discord_name", sa.String(100), nullable=False),
        sa.Column("choices", sa.JSON(), nullable=False),
    )
    op.create_table(
        "signup_interactions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "event_id",
            sa.String(36),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("response", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_signup_interactions_event_id", "signup_interactions", ["event_id"]
    )


def downgrade():
    op.drop_table("signup_interactions")
    op.drop_table("table_signups")
    op.drop_column("events", "signup_mode")
