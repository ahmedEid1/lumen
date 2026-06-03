"""S7pre.1 — AES-256-GCM envelope encryption (secrets_crypto).

Tests the BYOK envelope-encryption primitive from ADR-0027 §2:
per-secret random DEK, AES-256-GCM encrypt the plaintext under the DEK,
wrap the DEK under a versioned server KEK. Decryption is the only place
the plaintext re-materializes; tampering must surface as ``InvalidTag``.

These are pure-unit tests — no DB, no network. They drive ``encrypt`` /
``decrypt`` / ``key_fingerprint`` / ``last4`` / ``rotate_secret`` and the
dev-derived-KEK fallback policy (refused under ``ENV=production``).
"""

from __future__ import annotations

import base64
import os

import pytest
from cryptography.exceptions import InvalidTag

from app.core import secrets_crypto as sc
from app.core.config import Environment, get_settings


def _b64key() -> str:
    """A fresh base64-encoded 32-byte KEK."""
    return base64.b64encode(os.urandom(32)).decode("ascii")


@pytest.fixture(autouse=True)
def _isolate_kek(monkeypatch):
    """Each test gets its own KEK config + a cleared module cache.

    ``secrets_crypto`` caches the resolved active KEK; flip env then
    clear so a stale cache from a prior test can't bleed through.
    """
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("BYOK_MASTER_KEYS", f'{{"1": "{_b64key()}"}}')
    monkeypatch.setenv("BYOK_MASTER_KEY_VERSION", "1")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    sc.reset_for_tests()
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]
    sc.reset_for_tests()


def test_round_trip_identical():
    plaintext = b"sk-test-abcd1234567890ABCDEFGH"
    blob = sc.encrypt(plaintext)
    assert isinstance(blob, (bytes, bytearray))
    assert plaintext not in blob  # ciphertext, not plaintext-with-header
    assert sc.decrypt(blob) == plaintext


def test_each_encrypt_uses_fresh_dek_and_nonce():
    """Two encryptions of the same plaintext must differ (random DEK+nonce)."""
    pt = b"sk-same-secret-value-here-0000"
    a = sc.encrypt(pt)
    b = sc.encrypt(pt)
    assert a != b
    assert sc.decrypt(a) == pt
    assert sc.decrypt(b) == pt


def test_tamper_detected_invalid_tag():
    pt = b"sk-tamper-me-0000000000000000"
    blob = bytearray(sc.encrypt(pt))
    # Flip the last byte (inside the AES-GCM tag of the wrapped DEK or the
    # ciphertext, depending on layout) — either way auth must fail.
    blob[-1] ^= 0x01
    with pytest.raises(InvalidTag):
        sc.decrypt(bytes(blob))


def test_tamper_in_middle_detected():
    pt = b"sk-flip-the-middle-byte-000000"
    blob = bytearray(sc.encrypt(pt))
    mid = len(blob) // 2
    blob[mid] ^= 0xFF
    with pytest.raises(InvalidTag):
        sc.decrypt(bytes(blob))


def test_multi_version_decrypt(monkeypatch):
    """A blob wrapped under KEK v1 still decrypts after v2 becomes active."""
    v1 = _b64key()
    monkeypatch.setenv("BYOK_MASTER_KEYS", f'{{"1": "{v1}"}}')
    monkeypatch.setenv("BYOK_MASTER_KEY_VERSION", "1")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    sc.reset_for_tests()

    pt = b"sk-encrypted-under-v1-key-0000"
    blob_v1 = sc.encrypt(pt)

    # Introduce v2 and make it active; v1 retained for decrypt.
    v2 = _b64key()
    monkeypatch.setenv("BYOK_MASTER_KEYS", f'{{"1": "{v1}", "2": "{v2}"}}')
    monkeypatch.setenv("BYOK_MASTER_KEY_VERSION", "2")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    sc.reset_for_tests()

    # Old blob still decrypts (resolves KEK by the version embedded in the blob).
    assert sc.decrypt(blob_v1) == pt
    # New encryptions use v2 but also round-trip.
    blob_v2 = sc.encrypt(pt)
    assert sc.decrypt(blob_v2) == pt
    assert blob_v1 != blob_v2


def test_rotate_secret_rewraps_only_data_key(monkeypatch):
    """rotate_secret re-wraps enc_data_key under the new KEK; plaintext unchanged."""
    v1 = _b64key()
    monkeypatch.setenv("BYOK_MASTER_KEYS", f'{{"1": "{v1}"}}')
    monkeypatch.setenv("BYOK_MASTER_KEY_VERSION", "1")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    sc.reset_for_tests()

    pt = b"sk-rotate-me-please-0000000000"
    blob_v1 = sc.encrypt(pt)

    v2 = _b64key()
    monkeypatch.setenv("BYOK_MASTER_KEYS", f'{{"1": "{v1}", "2": "{v2}"}}')
    monkeypatch.setenv("BYOK_MASTER_KEY_VERSION", "2")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    sc.reset_for_tests()

    rotated = sc.rotate_secret(blob_v1)
    assert rotated != blob_v1
    # The rotated blob still decrypts to the same plaintext.
    assert sc.decrypt(rotated) == pt
    # Re-running rotate on an already-current-version blob is a no-op-ish
    # (still decrypts; idempotent against the active version).
    assert sc.decrypt(sc.rotate_secret(rotated)) == pt


def test_key_fingerprint_stable_and_distinct():
    a = b"sk-aaaa1111bbbb2222cccc3333"
    b = b"sk-different-secret-0000000000"
    assert sc.key_fingerprint(a) == sc.key_fingerprint(a)
    assert sc.key_fingerprint(a) != sc.key_fingerprint(b)
    # SHA-256 hex.
    assert len(sc.key_fingerprint(a)) == 64
    int(sc.key_fingerprint(a), 16)  # hex-parseable


def test_last4():
    assert sc.last4(b"sk-secretXYZ9") == "XYZ9"
    assert sc.last4("sk-secretXYZ9") == "XYZ9"
    assert sc.last4(b"ab") == "****"  # too short to safely reveal


def test_no_plaintext_in_repr_or_str():
    """The encrypted blob's repr/str must never contain the plaintext."""
    pt = b"sk-super-secret-never-log-this"
    blob = sc.encrypt(pt)
    assert b"super-secret" not in repr(blob).encode()
    assert "super-secret" not in str(blob)


def test_derived_kek_works_in_dev_test(monkeypatch):
    """With no BYOK_MASTER_KEYS, a dev-derived KEK from secret_key is used
    (ENV != production)."""
    monkeypatch.setenv("ENV", "test")
    monkeypatch.delenv("BYOK_MASTER_KEYS", raising=False)
    monkeypatch.delenv("BYOK_MASTER_KEY_VERSION", raising=False)
    monkeypatch.setenv("SECRET_KEY", "test-secret-please-change-this-is-a-long-enough-key-x")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    sc.reset_for_tests()

    pt = b"sk-derived-kek-roundtrip-00000"
    blob = sc.encrypt(pt)
    assert sc.decrypt(blob) == pt


def test_derived_kek_refused_in_production(monkeypatch):
    """In production, a missing/derived KEK must hard-fail — never silently
    derive from secret_key."""
    monkeypatch.setenv("ENV", "production")
    monkeypatch.delenv("BYOK_MASTER_KEYS", raising=False)
    monkeypatch.delenv("BYOK_MASTER_KEY_VERSION", raising=False)
    get_settings.cache_clear()  # type: ignore[attr-defined]
    sc.reset_for_tests()
    try:
        with pytest.raises(RuntimeError):
            sc.encrypt(b"sk-should-not-encrypt-in-prod0")
    finally:
        monkeypatch.setenv("ENV", "test")
        get_settings.cache_clear()  # type: ignore[attr-defined]
        sc.reset_for_tests()


def test_settings_expose_byok_master_keys(monkeypatch):
    """The KEK map + version live on Settings (config.py)."""
    monkeypatch.setenv("BYOK_MASTER_KEYS", f'{{"1": "{_b64key()}"}}')
    monkeypatch.setenv("BYOK_MASTER_KEY_VERSION", "1")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    s = get_settings()
    assert hasattr(s, "byok_master_keys")
    assert hasattr(s, "byok_master_key_version")
    assert s.byok_master_key_version == 1
    assert 1 in s.byok_master_keys
    # Production is the env where the derived fallback is forbidden.
    assert Environment.production == Environment("production")
