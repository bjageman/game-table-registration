"""Keep the short-notice exception independent of its configured hours."""

import sqlalchemy as sa
from alembic import op

revision = "20261123_short_notice"
down_revision = "20261122_waitlist_guarantees"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "assignment_preferences",
        sa.Column(
            "keep_waitlist_guarantee_on_short_notice",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    preferences = sa.table(
        "assignment_preferences",
        sa.column("keep_waitlist_guarantee_on_short_notice", sa.Boolean()),
        sa.column("waitlist_guarantee_retention_hours", sa.Integer()),
    )
    op.execute(
        preferences.update()
        .where(preferences.c.waitlist_guarantee_retention_hours == 0)
        .values(
            keep_waitlist_guarantee_on_short_notice=False,
            waitlist_guarantee_retention_hours=5,
        )
    )


def downgrade():
    preferences = sa.table(
        "assignment_preferences",
        sa.column("keep_waitlist_guarantee_on_short_notice", sa.Boolean()),
        sa.column("waitlist_guarantee_retention_hours", sa.Integer()),
    )
    op.execute(
        preferences.update()
        .where(preferences.c.keep_waitlist_guarantee_on_short_notice.is_(False))
        .values(waitlist_guarantee_retention_hours=0)
    )
    op.drop_column("assignment_preferences", "keep_waitlist_guarantee_on_short_notice")
