"""Carry existing guild weight choices into organization and personal scopes."""

import sqlalchemy as sa
from alembic import op

revision = "20261104_assignment_backfill"
down_revision = "20261104_assignment_preferences"
branch_labels = None
depends_on = None


def upgrade():
    db = op.get_bind()
    weights = {
        row.guild_id: bool(row.automatic_weight_adjustment)
        for row in db.execute(
            sa.text("SELECT guild_id, automatic_weight_adjustment FROM guild_settings")
        )
    }
    if not weights:
        return
    scoped: dict[str, bool] = {}
    for row in db.execute(sa.text("SELECT id, guild_id FROM organizations")):
        if row.guild_id in weights:
            scoped[f"org:{row.id}"] = weights[row.guild_id]
    for row in db.execute(
        sa.text(
            "SELECT user_id, guild_id FROM user_settings WHERE disconnected = false"
        )
    ):
        if row.guild_id in weights:
            scoped[f"user:{row.user_id}"] = weights[row.guild_id]
    for row in db.execute(
        sa.text(
            "SELECT DISTINCT created_by, guild_id FROM events "
            "WHERE organization_id IS NULL"
        )
    ):
        if row.guild_id in weights:
            scoped.setdefault(f"user:{row.created_by}", weights[row.guild_id])
    existing = set(
        db.execute(sa.text("SELECT scope_key FROM assignment_preferences")).scalars()
    )
    for key, enabled in scoped.items():
        if key in existing:
            continue
        db.execute(
            sa.text(
                "INSERT INTO assignment_preferences "
                "(scope_key, automatic_weight_adjustment, announce_table_changes) "
                "VALUES (:scope_key, :enabled, false)"
            ),
            {"scope_key": key, "enabled": enabled},
        )


def downgrade():
    # The legacy guild settings are kept, so no data needs to be removed.
    pass
