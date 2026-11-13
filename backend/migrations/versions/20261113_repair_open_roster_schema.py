"""Repair partially applied open roster schema changes."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "20261113_repair_open_roster_schema"
down_revision = "20261112_open_signup_rosters"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        # Alembic defaults to VARCHAR(32), shorter than this revision ID.
        # Keep the ID stable for SQLite databases that already applied it.
        op.alter_column(
            "alembic_version",
            "version_num",
            existing_type=sa.String(32),
            type_=sa.String(64),
            existing_nullable=False,
        )
    inspector = inspect(connection)
    event_columns = {column["name"] for column in inspector.get_columns("events")}
    if "signup_roster_hash" not in event_columns:
        op.add_column("events", sa.Column("signup_roster_hash", sa.String(64)))
    if "signup_roster_checked_at" not in event_columns:
        op.add_column("events", sa.Column("signup_roster_checked_at", sa.Float()))
    if "signup_roster_messages" not in event_columns:
        op.add_column("events", sa.Column("signup_roster_messages", sa.JSON()))

    preference_columns = {
        column["name"] for column in inspector.get_columns("assignment_preferences")
    }
    if "show_open_signup_players" not in preference_columns:
        op.add_column(
            "assignment_preferences",
            sa.Column(
                "show_open_signup_players",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )


def downgrade():
    # These columns belong to the preceding feature revision. The repair only
    # fills in columns missing from databases that already recorded that
    # revision, so reverting this marker must leave its schema intact.
    # Keep version_num widened: Alembic updates it after downgrade() returns,
    # so it still contains the longer revision ID during this function.
    pass
