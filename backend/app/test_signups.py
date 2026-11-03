"""Persist synthetic participants behind an operator-only allowlist."""

import hashlib
import random
import secrets
from typing import Any

from app.config import Settings


def allowed(user_id: str, config: Settings) -> bool:
    ids = {
        value.strip()
        for value in config.test_signup_user_ids.split(",")
        if value.strip()
    }
    if config.owner_discord_id:
        ids.add(config.owner_discord_id)
    return user_id in ids


def generate(event_id: str, tables: list[dict[str, Any]], count: int) -> dict[str, Any]:
    seed = secrets.token_hex(16)
    rng = random.Random(seed)
    names = [table["name"] for table in tables]
    return {
        "generation": seed,
        "players": [
            {
                "id": "test-"
                + hashlib.sha256(f"{event_id}:{seed}:{i}".encode()).hexdigest()[:24],
                "name": f"Test Player {i + 1:03d}",
                "choices": rng.sample(names, rng.randint(1, len(names))),
                "weight": rng.choice([0.5, 1.0, 2.0]),
            }
            for i in range(count)
        ],
    }


def add_to_rows(
    rows: list[dict[str, Any]], population: dict[str, Any] | None
) -> list[dict[str, Any]]:
    if population:
        for row in rows:
            row["players"] = [
                *row["players"],
                *[
                    {"id": p["id"], "name": p["name"]}
                    for p in population["players"]
                    if row["name"] in p["choices"]
                ],
            ]
    return rows
