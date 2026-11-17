"""Replace single linked players with reciprocal unordered preferences."""

import sqlalchemy as sa
from alembic import op

revision = "20261124_player_preferences"
down_revision = "20261123_short_notice"
branch_labels = None
depends_on = None


def upgrade():
    table = op.create_table(
        "player_preferences",
        sa.Column("scope_key", sa.String(100), primary_key=True),
        sa.Column("guild_id", sa.String(32), primary_key=True),
        sa.Column("player_id", sa.String(32), primary_key=True),
        sa.Column("preferred_id", sa.String(32), primary_key=True),
        sa.CheckConstraint(
            "player_id < preferred_id", name="ck_player_preference_order"
        ),
    )
    bind = op.get_bind()
    rows = list(
        bind.execute(
            sa.text(
                "SELECT scope_key, guild_id, discord_id, partner_id "
                "FROM player_profiles"
            )
        ).mappings()
    )
    links = {
        (r["scope_key"], r["guild_id"], r["discord_id"]): r["partner_id"] for r in rows
    }
    edges = [
        {
            "scope_key": scope,
            "guild_id": guild,
            "player_id": pid,
            "preferred_id": partner,
        }
        for (scope, guild, pid), partner in links.items()
        if partner and pid < partner and links.get((scope, guild, partner)) == pid
    ]
    if edges:
        bind.execute(table.insert(), edges)
    with op.batch_alter_table("player_profiles") as batch:
        batch.drop_column("partner_id")
    op.add_column("events", sa.Column("close_preferences", sa.JSON(), nullable=True))


def downgrade():
    op.add_column(
        "player_profiles", sa.Column("partner_id", sa.String(32), nullable=True)
    )
    bind = op.get_bind()
    # The old schema can retain only disjoint pairs; choose them deterministically.
    used = set()
    rows = list(
        bind.execute(
            sa.text(
                "SELECT * FROM player_preferences "
                "ORDER BY scope_key, guild_id, player_id, preferred_id"
            )
        ).mappings()
    )
    for row in rows:
        scope, guild = row["scope_key"], row["guild_id"]
        a, b = row["player_id"], row["preferred_id"]
        if (scope, guild, a) in used or (scope, guild, b) in used:
            continue
        for pid, partner in ((a, b), (b, a)):
            bind.execute(
                sa.text(
                    "UPDATE player_profiles SET partner_id = :partner "
                    "WHERE scope_key = :scope AND guild_id = :guild "
                    "AND discord_id = :pid"
                ),
                {"scope": scope, "guild": guild, "pid": pid, "partner": partner},
            )
            used.add((scope, guild, pid))
    op.drop_column("events", "close_preferences")
    op.drop_table("player_preferences")
