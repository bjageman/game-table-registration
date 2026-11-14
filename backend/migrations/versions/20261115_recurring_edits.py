"""Keep occurrence identity when events are moved or published."""

import sqlalchemy as sa
from alembic import op

revision = "20261115_recurring_edits"
down_revision = "20261114_signup_warnings"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("events") as batch:
        batch.add_column(sa.Column("source_series_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("series_slot_at", sa.Float(), nullable=True))
        batch.create_foreign_key(
            "fk_event_source_series",
            "recurring_series",
            ["source_series_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_events_source_series_id", ["source_series_id"])
        batch.create_unique_constraint(
            "uq_event_series_slot", ["source_series_id", "series_slot_at"]
        )
    op.execute(
        "UPDATE events SET source_series_id = series_id, series_slot_at = starts_at "
        "WHERE series_id IS NOT NULL"
    )
    op.execute(
        "UPDATE events SET series_id = NULL WHERE published_at IS NOT NULL "
        "OR message_id IS NOT NULL"
    )


def downgrade():
    op.execute(
        "UPDATE events SET series_id = source_series_id "
        "WHERE source_series_id IS NOT NULL"
    )
    with op.batch_alter_table("events") as batch:
        batch.drop_constraint("uq_event_series_slot", type_="unique")
        batch.drop_index("ix_events_source_series_id")
        batch.drop_constraint("fk_event_source_series", type_="foreignkey")
        batch.drop_column("series_slot_at")
        batch.drop_column("source_series_id")
