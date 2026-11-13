"""Enable General options by default while preserving stored preferences."""

import sqlalchemy as sa
from alembic import op

revision = "20261113_general_defaults"
down_revision = "20261113_waitlist_additions"
branch_labels = None
depends_on = None

OPTIONS = (
    "automatic_weight_adjustment",
    "announce_table_changes",
    "post_discord_updates_to_thread",
    "show_open_signup_players",
    "dm_waitlist_promotions",
)


def upgrade():
    with op.batch_alter_table("assignment_preferences") as batch:
        for name in OPTIONS:
            batch.alter_column(
                name, existing_type=sa.Boolean(), server_default=sa.true()
            )


def downgrade():
    with op.batch_alter_table("assignment_preferences") as batch:
        for name in OPTIONS:
            batch.alter_column(
                name,
                existing_type=sa.Boolean(),
                server_default=sa.false()
                if name in {"show_open_signup_players", "dm_waitlist_promotions"}
                else None,
            )
