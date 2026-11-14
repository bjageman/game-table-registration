"""Optional closing warnings for events, recurring schedules, and templates."""

import sqlalchemy as sa
from alembic import op

revision = "20261114_signup_warnings"
down_revision = "20261114_player_pairs"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("events", "recurring_series", "event_templates"):
        op.add_column(
            table,
            sa.Column(
                "post_warning_message",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
        op.add_column(
            table,
            sa.Column(
                "warning_hours_before_close",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
        )
        op.add_column(
            table,
            sa.Column(
                "warning_message", sa.String(1600), nullable=False, server_default=""
            ),
        )


def downgrade():
    for table in ("event_templates", "recurring_series", "events"):
        op.drop_column(table, "warning_message")
        op.drop_column(table, "warning_hours_before_close")
        op.drop_column(table, "post_warning_message")
