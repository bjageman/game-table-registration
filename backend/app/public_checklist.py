"""Opaque player identifiers scoped to one public assignment link."""

import hashlib
import hmac


def public_player_id(token: str, player_id: str) -> str:
    return hmac.new(token.encode(), player_id.encode(), hashlib.sha256).hexdigest()
