"""Add descriptions to events and reusable templates."""

import sqlalchemy as sa
from alembic import op

revision = "20261104_event_description"
down_revision = "20261103_organizations"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("events") as batch:
        batch.add_column(
            sa.Column("description", sa.String(300), nullable=False, server_default="")
        )
    with op.batch_alter_table("event_templates") as batch:
        batch.add_column(
            sa.Column("description", sa.String(300), nullable=False, server_default="")
        )


def downgrade():
    with op.batch_alter_table("event_templates") as batch:
        batch.drop_column("description")
    with op.batch_alter_table("events") as batch:
        batch.drop_column("description")
