"""Add optional locations to events and templates."""

import sqlalchemy as sa
from alembic import op

revision = "20261104_event_location"
down_revision = "20261104_event_description"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("events") as batch:
        batch.add_column(
            sa.Column("location", sa.String(200), nullable=False, server_default="")
        )
    with op.batch_alter_table("event_templates") as batch:
        batch.add_column(
            sa.Column("location", sa.String(200), nullable=False, server_default="")
        )


def downgrade():
    with op.batch_alter_table("event_templates") as batch:
        batch.drop_column("location")
    with op.batch_alter_table("events") as batch:
        batch.drop_column("location")
