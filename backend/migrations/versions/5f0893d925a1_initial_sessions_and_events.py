"""Initial sessions and events"""

import sqlalchemy as sa
from alembic import op

revision = "5f0893d925a1"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("guild_id", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=100), nullable=False),
        sa.Column("starts_at", sa.Float(), nullable=False),
        sa.Column("duration_hours", sa.Integer(), nullable=False),
        sa.Column("tables", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.String(length=32), nullable=False),
        sa.Column("message_id", sa.String(length=32), nullable=True),
        sa.Column("closes_at", sa.Float(), nullable=True),
        sa.Column("answers", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_events_guild_id"), "events", ["guild_id"], unique=False)
    op.create_table(
        "login_states",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("token_hash"),
    )
    op.create_table(
        "sessions",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("username", sa.String(length=100), nullable=False),
        sa.Column("csrf", sa.String(length=100), nullable=False),
        sa.Column("expires", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("token_hash"),
    )


def downgrade():
    op.drop_table("sessions")
    op.drop_table("login_states")
    op.drop_index(op.f("ix_events_guild_id"), table_name="events")
    op.drop_table("events")
