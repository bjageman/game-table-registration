"""Token hashing shared by authentication and tests."""

import hashlib


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
