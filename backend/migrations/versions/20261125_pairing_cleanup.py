"""Remove the obsolete single-partner closing snapshot."""

import sqlalchemy as sa
from alembic import op

revision = "20261125_pairing_cleanup"
down_revision = "20261124_player_preferences"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column("events", "close_pairs")


def downgrade():
    op.add_column("events", sa.Column("close_pairs", sa.JSON(), nullable=True))
