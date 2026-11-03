"""Add organizations, membership, selection, and event ownership."""

import sqlalchemy as sa
from alembic import op

revision = "20261103_organizations"
down_revision = "20261102_event_manager_signups"
branch_labels = None
depends_on = None


def upgrade():
    # SQLite DDL is not transactional. A stopped local upgrade may have created
    # some objects while alembic_version still points at the previous revision.
    def exists(table: str) -> bool:
        return sa.inspect(op.get_bind()).has_table(table)

    if not exists("user_identities"):
        op.create_table(
            "user_identities",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("username", sa.String(100), nullable=False),
        )
    if not exists("organizations"):
        op.create_table(
            "organizations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("normalized_name", sa.String(100), nullable=False, unique=True),
            sa.Column("created_by", sa.String(32), nullable=False),
            sa.Column("guild_id", sa.String(32), nullable=False),
            sa.Column("channel_id", sa.String(32), nullable=False),
        )
    if not exists("organization_members"):
        op.create_table(
            "organization_members",
            sa.Column(
                "organization_id",
                sa.String(36),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("user_id", sa.String(32), primary_key=True),
            sa.Column("role", sa.String(16), nullable=False),
        )
    if not exists("organization_selections"):
        op.create_table(
            "organization_selections",
            sa.Column("user_id", sa.String(32), primary_key=True),
            sa.Column(
                "organization_id",
                sa.String(36),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
        )
    if "organization_id" not in {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("events")
    }:
        with op.batch_alter_table("events") as batch:
            batch.add_column(
                sa.Column(
                    "organization_id",
                    sa.String(36),
                    sa.ForeignKey(
                        "organizations.id",
                        ondelete="SET NULL",
                        name="fk_events_organization_id",
                    ),
                    nullable=True,
                )
            )
    if "ix_events_organization_id" not in {
        index["name"] for index in sa.inspect(op.get_bind()).get_indexes("events")
    }:
        op.create_index("ix_events_organization_id", "events", ["organization_id"])
    # Existing events were shared by destination. Keep them visible to their creators.


def downgrade():
    op.drop_index("ix_events_organization_id", "events")
    with op.batch_alter_table("events") as batch:
        batch.drop_column("organization_id")
    op.drop_table("organization_selections")
    op.drop_table("organization_members")
    op.drop_table("organizations")
    op.drop_table("user_identities")
