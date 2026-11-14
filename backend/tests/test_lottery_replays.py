"""Golden draws captured before extracting shared deterministic sampling."""

import hashlib
import json
from pathlib import Path

import pytest

from app.assignments.lottery import assign

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures/lottery_replays.json").read_text()
)


@pytest.mark.parametrize("case", FIXTURES["cases"])
def test_shared_sampling_preserves_existing_draws(case):
    result = assign({**FIXTURES["snapshot"], "pairs": case["pairs"]}, case["seed"])
    actual = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
    assert actual == case["sha256"]
