"""Stable seed/label sampling shared by individual and paired draws."""

import hashlib
import math


def digest(seed: str, label: str) -> str:
    return hashlib.sha256(f"{seed}\0{label}".encode()).hexdigest()


def weighted_priority(seed: str, label: str, weight: float) -> float:
    # The same 52-bit sample and operation order keep saved draws replayable.
    uniform = (int(digest(seed, f"priority:{label}")[:13], 16) + 1) / (2**52 + 1)
    return -math.log(uniform) / weight
