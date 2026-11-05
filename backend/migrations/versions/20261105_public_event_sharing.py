"""Add opt-in public assignment links."""

import sqlalchemy as sa
from alembic import op

revision = "20261105_public_event_sharing"
down_revision = "20261104_repeated_events"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("events") as batch:
        batch.add_column(sa.Column("public_share_token", sa.String(64), nullable=True))
        batch.create_unique_constraint(
            "uq_events_public_share_token", ["public_share_token"]
        )


def downgrade():
    with op.batch_alter_table("events") as batch:
        batch.drop_constraint("uq_events_public_share_token", type_="unique")
        batch.drop_column("public_share_token")
