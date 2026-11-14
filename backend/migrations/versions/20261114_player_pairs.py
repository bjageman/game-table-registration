"""Independent organization player profiles and reciprocal player pairs."""

import sqlalchemy as sa
from alembic import op

revision = "20261114_player_pairs"
down_revision = "20261113_assignment_review"
branch_labels = None
depends_on = None


def profile_table(name, scoped):
    columns = (
        [sa.Column("scope_key", sa.String(100), primary_key=True)] if scoped else []
    )
    columns += [
        sa.Column("guild_id", sa.String(32), primary_key=True),
        sa.Column("discord_id", sa.String(32), primary_key=True),
        sa.Column("discord_name", sa.String(100), nullable=False),
        sa.Column("guaranteed_seat", sa.Boolean(), nullable=False),
        sa.Column("is_test", sa.Boolean(), nullable=False),
        sa.Column("real_name", sa.String(100), nullable=False),
        sa.Column("weighting", sa.Float(), nullable=False),
    ]
    if scoped:
        columns.append(sa.Column("partner_id", sa.String(32), nullable=True))
    return op.create_table(name, *columns)


def upgrade():
    bind = op.get_bind()
    old = list(bind.execute(sa.text("SELECT * FROM player_profiles")).mappings())
    scopes = {}
    for row in bind.execute(
        sa.text("SELECT organization_id, created_by, guild_id FROM events")
    ).mappings():
        key = (
            f"org:{row['organization_id']}"
            if row["organization_id"]
            else f"user:{row['created_by']}"
        )
        scopes.setdefault(row["guild_id"], set()).add(key)
    for row in bind.execute(
        sa.text("SELECT id, guild_id FROM organizations")
    ).mappings():
        if row["guild_id"]:
            scopes.setdefault(row["guild_id"], set()).add(f"org:{row['id']}")
    for row in bind.execute(
        sa.text("SELECT user_id, guild_id FROM user_settings")
    ).mappings():
        scopes.setdefault(row["guild_id"], set()).add(f"user:{row['user_id']}")
    table = profile_table("scoped_player_profiles", True)
    rows = [
        {**dict(row), "scope_key": key, "partner_id": None}
        for row in old
        for key in sorted(scopes.get(row["guild_id"], {f"legacy:{row['guild_id']}"}))
    ]
    if rows:
        bind.execute(table.insert(), rows)
    op.drop_table("player_profiles")
    op.rename_table("scoped_player_profiles", "player_profiles")
    op.add_column("events", sa.Column("close_pairs", sa.JSON(), nullable=True))


def downgrade():
    bind = op.get_bind()
    # A downgrade can represent only one profile per Discord server/player.
    # Pick a deterministic copy; independent profiles are never joined at runtime.
    rows = {}
    for record in bind.execute(
        sa.text("SELECT * FROM player_profiles ORDER BY scope_key")
    ).mappings():
        row = dict(record)
        row.pop("scope_key")
        row.pop("partner_id")
        rows.setdefault((row["guild_id"], row["discord_id"]), row)
    table = profile_table("unscoped_player_profiles", False)
    if rows:
        bind.execute(table.insert(), list(rows.values()))
    op.drop_table("player_profiles")
    op.rename_table("unscoped_player_profiles", "player_profiles")
    op.drop_column("events", "close_pairs")
