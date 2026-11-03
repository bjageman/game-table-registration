"""Automatic weight adjustments and a one-time reset of existing profiles."""

import sqlalchemy as sa
from alembic import op

revision = "20261101_weight_adjustments"
down_revision = "20261101_archive_events"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "guild_settings",
        sa.Column("guild_id", sa.String(32), primary_key=True),
        sa.Column(
            "automatic_weight_adjustment",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "events", sa.Column("close_adjust_weights", sa.Boolean(), nullable=True)
    )
    op.execute(sa.text("UPDATE player_profiles SET weighting = 1.0"))


def downgrade():
    op.drop_column("events", "close_adjust_weights")
    op.drop_table("guild_settings")
