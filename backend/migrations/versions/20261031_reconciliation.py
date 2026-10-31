"""Final voter snapshots, reconciliation retries and withdrawals."""

import sqlalchemy as sa
from alembic import op

revision = "20261031_voters"
down_revision = "20261031_recur"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("events", sa.Column("voter_snapshot", sa.JSON(), nullable=True))
    op.add_column("events", sa.Column("reconciled_at", sa.Float(), nullable=True))
    op.add_column(
        "events",
        sa.Column(
            "reconciliation_attempts", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column("events", sa.Column("reconcile_after", sa.Float(), nullable=True))
    op.add_column(
        "events",
        sa.Column("recovery_audit", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.create_table(
        "withdrawals",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(32), primary_key=True),
        sa.Column("created_at", sa.Float(), nullable=False),
    )

    op.create_table(
        "live_votes",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(32), primary_key=True),
        sa.Column("answer_id", sa.Integer(), primary_key=True),
    )


def downgrade():
    op.drop_table("live_votes")
    op.drop_table("withdrawals")
    for column in (
        "recovery_audit",
        "reconcile_after",
        "reconciliation_attempts",
        "reconciled_at",
        "voter_snapshot",
    ):
        op.drop_column("events", column)
