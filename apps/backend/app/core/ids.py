"""Short opaque IDs (nanoid, 21 chars, URL-safe)."""

from __future__ import annotations

from nanoid import generate

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def new_id() -> str:
    return generate(ALPHABET, size=21)
