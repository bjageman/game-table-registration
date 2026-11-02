"""Track reliable reaction snapshots across reconnects and deadlines."""

import sqlalchemy as sa
from alembic import op

revision = "20261101_reaction_signups"
down_revision = "20261101_custom_signups"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("events", sa.Column("reaction_checkpoint", sa.Float(), nullable=True))
    op.add_column("events", sa.Column("reaction_error", sa.String(500), nullable=True))


def downgrade():
    op.drop_column("events", "reaction_error")
    op.drop_column("events", "reaction_checkpoint")
