"""Move saved weights onto the five-point baseline."""

from decimal import Decimal

import sqlalchemy as sa
from alembic import op

revision = "20261105_weight_scale_five"
down_revision = "20261105_public_event_sharing"
branch_labels = None
depends_on = None


def rescale(multiplier):
    connection = op.get_bind()
    for name, keys in (
        ("player_profiles", ("guild_id", "discord_id")),
        ("event_player_settings", ("event_id", "discord_id")),
    ):
        table = sa.Table(name, sa.MetaData(), autoload_with=connection)
        for row in connection.execute(
            sa.select(table).where(table.c.weighting.is_not(None))
        ).mappings():
            weight = float(
                min(
                    Decimal("10"),
                    max(Decimal("0.1"), Decimal(str(row["weighting"])) * multiplier),
                )
            )
            connection.execute(
                table.update()
                .where(*(table.c[key] == row[key] for key in keys))
                .values(weighting=weight)
            )


def upgrade():
    rescale(Decimal("5"))


def downgrade():
    # Values capped at ten during upgrade cannot recover their original value.
    rescale(Decimal("0.2"))
