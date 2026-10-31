"""Persistent player profiles independent of events and polls."""

import sqlalchemy as sa
from alembic import op

revision = "20261031_profiles"
down_revision = "5f0893d925a1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "player_profiles",
        sa.Column("guild_id", sa.String(32), primary_key=True),
        sa.Column("discord_id", sa.String(32), primary_key=True),
        sa.Column("discord_name", sa.String(100), nullable=False),
        sa.Column("real_name", sa.String(100), nullable=False),
        sa.Column("weighting", sa.Float(), nullable=False),
    )


def downgrade():
    op.drop_table("player_profiles")
