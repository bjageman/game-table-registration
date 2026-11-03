"""Remove specific table reservations; guarantees use selected tables."""

import sqlalchemy as sa
from alembic import op

revision = "20261101_selected_guarantees"
down_revision = "20261101_guarantees"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column("player_profiles", "guaranteed_table")
    # Discard old frozen reservation settings without altering saved lottery runs.
    op.execute(
        sa.text("UPDATE events SET close_guarantees = NULL WHERE status != 'assigned'")
    )


def downgrade():
    op.add_column(
        "player_profiles", sa.Column("guaranteed_table", sa.String(35), nullable=True)
    )
