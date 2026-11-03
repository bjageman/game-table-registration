"""Per-user Discord destinations and immutable event channels."""

import sqlalchemy as sa
from alembic import op

revision = "20261031_destinations"
down_revision = "20261031_profiles"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "sessions", sa.Column("guilds", sa.JSON(), nullable=False, server_default="[]")
    )
    op.add_column("events", sa.Column("channel_id", sa.String(32), nullable=True))
    from app.config import Settings

    defaults = Settings()
    if defaults.discord_guild_id and defaults.discord_channel_id:
        events = sa.table("events", sa.column("guild_id"), sa.column("channel_id"))
        op.get_bind().execute(
            events.update()
            .where(
                events.c.guild_id == defaults.discord_guild_id,
                events.c.channel_id.is_(None),
            )
            .values(channel_id=defaults.discord_channel_id)
        )
    op.create_table(
        "user_settings",
        sa.Column("user_id", sa.String(32), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("guild_name", sa.String(100), nullable=False),
        sa.Column("channel_id", sa.String(32), nullable=False),
        sa.Column("channel_name", sa.String(100), nullable=False),
    )


def downgrade():
    op.drop_table("user_settings")
    op.drop_column("events", "channel_id")
    op.drop_column("sessions", "guilds")
