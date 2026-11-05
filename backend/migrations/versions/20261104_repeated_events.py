"""Store recurring schedules and their upcoming occurrences."""

import sqlalchemy as sa
from alembic import op

revision = "20261104_repeated_events"
down_revision = "20261104_assignment_backfill"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "recurring_series",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_by", sa.String(32), nullable=False),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="SET NULL"),
        ),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("channel_id", sa.String(32), nullable=False),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("description", sa.String(300), nullable=False),
        sa.Column("location", sa.String(200), nullable=False),
        sa.Column("tables", sa.JSON(), nullable=False),
        sa.Column("first_local", sa.String(16), nullable=False),
        sa.Column("time_zone", sa.String(100), nullable=False),
        sa.Column("frequency", sa.String(16), nullable=False),
        sa.Column("opens_before_hours", sa.Integer(), nullable=False),
        sa.Column("closes_before_hours", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
    )
    op.create_index(
        "ix_recurring_series_organization_id", "recurring_series", ["organization_id"]
    )
    op.create_table(
        "canceled_occurrences",
        sa.Column(
            "series_id",
            sa.String(36),
            sa.ForeignKey("recurring_series.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("starts_at", sa.Float(), primary_key=True),
    )
    with op.batch_alter_table("events") as batch:
        batch.add_column(
            sa.Column(
                "series_id",
                sa.String(36),
                sa.ForeignKey(
                    "recurring_series.id",
                    name="fk_events_series_id_recurring_series",
                    ondelete="SET NULL",
                ),
            )
        )
        batch.add_column(sa.Column("scheduled_publish_at", sa.Float()))
        batch.create_index("ix_events_series_id", ["series_id"])
        batch.create_unique_constraint(
            "uq_events_series_start", ["series_id", "starts_at"]
        )


def downgrade():
    with op.batch_alter_table("events") as batch:
        batch.drop_constraint("uq_events_series_start", type_="unique")
        batch.drop_index("ix_events_series_id")
        batch.drop_column("scheduled_publish_at")
        batch.drop_column("series_id")
    op.drop_table("canceled_occurrences")
    op.drop_index("ix_recurring_series_organization_id", table_name="recurring_series")
    op.drop_table("recurring_series")
