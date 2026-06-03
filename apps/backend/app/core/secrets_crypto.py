"""AES-256-GCM envelope encryption for BYOK credential material.

S7-pre.1 / ADR-0027 §2. Each secret is encrypted with a fresh random
256-bit **DEK** (data-encryption key); the DEK is then wrapped under a
versioned server **KEK** (key-encryption key). This envelope scheme means
rotation only re-wraps the (small) wrapped-DEK — never re-touches the
plaintext (FR-BYOK-09/12).

Why a *self-describing blob* (vs. ADR-0027's three-column EncryptedSecret):
S7-pre ships the primitive ahead of the ``user_llm_credentials`` table, so
the public surface here is ``encrypt(bytes) -> bytes`` /
``decrypt(bytes) -> bytes`` per the IMPLEMENTATION-PLAN signature. The KEK
version, wrapped DEK, and ciphertext are packed into one opaque blob whose
header carries the wrapping version, so multi-version decrypt + rotation
work without a separate column. S5 can adapt this to the column layout
without changing the crypto.

Blob layout (all integers big-endian)::

    MAGIC(4) | kek_version(4) | len(enc_data_key)(2) | enc_data_key | enc_key

where each ``enc_*`` is ``nonce(12) || AESGCM-ciphertext-with-tag``.

**KEK source (FR-BYOK-10/11, R-S3):** ``Settings.byok_master_keys`` maps an
int version → base64(32-byte key); ``byok_master_key_version`` selects the
active wrapping version. When the map is empty AND ``ENV != production`` a
clearly-ephemeral KEK is derived from ``secret_key`` (domain-separated
SHA-256, mirroring ``badges_keys.py``). In production an empty/derived KEK
is a hard ``RuntimeError`` — the boot guard (``prod_guards.py``) catches it
earlier, but this module also refuses at the call site as defense in depth.

Nothing in this module logs or ``repr``s plaintext or key material.
"""

from __future__ import annotations

import base64
import hashlib
import os
import struct

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import Environment, get_settings

_MAGIC = b"LBK1"  # "Lumen BYOK envelope, v1"
_NONCE_LEN = 12
_KEK_LEN = 32  # AES-256
_HEADER = struct.Struct(">4sIH")  # MAGIC, kek_version, len(enc_data_key)

# Domain-separation tag for the dev-derived KEK. Distinct from the badges
# Ed25519 seed tag so the two key materials can never be confused even
# though both feed off ``secret_key``.
_DEV_KEK_DOMAIN = b"lumen.byok.kek.v1:"

# Module-level cache of the resolved KEK map. Cleared by ``reset_for_tests``
# whenever env vars flip mid-run (the Settings cache is cleared separately
# by the caller). Shape: ``{version:int -> 32-byte key}`` plus a record of
# whether the active version is a dev-derived fallback.
_kek_cache: dict[int, bytes] | None = None
_active_version_cache: int | None = None
_active_is_derived_cache: bool = False


def reset_for_tests() -> None:
    """Drop the cached KEK material so a test can flip env + reconfigure."""
    global _kek_cache, _active_version_cache, _active_is_derived_cache
    _kek_cache = None
    _active_version_cache = None
    _active_is_derived_cache = False


def _decode_kek(raw: str, *, version: int) -> bytes:
    try:
        key = base64.b64decode(raw, validate=True)
    except (ValueError, base64.binascii.Error) as exc:  # type: ignore[attr-defined]
        raise RuntimeError(f"BYOK_MASTER_KEYS[{version}] is not valid base64") from exc
    if len(key) != _KEK_LEN:
        raise RuntimeError(
            f"BYOK_MASTER_KEYS[{version}] must decode to exactly {_KEK_LEN} bytes "
            f"(AES-256), got {len(key)}"
        )
    return key


def _load_keks() -> tuple[dict[int, bytes], int, bool]:
    """Resolve the (versioned KEK map, active version, is-derived) triple.

    Caches the result; ``reset_for_tests`` clears it. Raises ``RuntimeError``
    in production when no real KEK is configured (never silently derive).
    """
    global _kek_cache, _active_version_cache, _active_is_derived_cache
    if _kek_cache is not None and _active_version_cache is not None:
        return _kek_cache, _active_version_cache, _active_is_derived_cache

    s = get_settings()
    raw_map = getattr(s, "byok_master_keys", {}) or {}
    keks: dict[int, bytes] = {}
    for version, secret in raw_map.items():
        raw = secret.get_secret_value() if hasattr(secret, "get_secret_value") else str(secret)
        if not raw:
            continue
        keks[int(version)] = _decode_kek(raw, version=int(version))

    if keks:
        active = int(getattr(s, "byok_master_key_version", 1))
        if active not in keks:
            raise RuntimeError(
                f"BYOK_MASTER_KEY_VERSION={active} has no matching key in "
                f"BYOK_MASTER_KEYS (versions present: {sorted(keks)})"
            )
        _kek_cache, _active_version_cache, _active_is_derived_cache = keks, active, False
        return keks, active, False

    # No real KEK configured. Production refuses; dev/test derives a
    # clearly-ephemeral KEK from secret_key.
    if s.env == Environment.production:
        raise RuntimeError(
            "BYOK master key (KEK) is not configured in production. Set "
            'BYOK_MASTER_KEYS={"1":"<base64 32-byte key>"} + '
            "BYOK_MASTER_KEY_VERSION=1. Refusing to derive a KEK from "
            "SECRET_KEY in production."
        )
    derived = hashlib.sha256(
        _DEV_KEK_DOMAIN + s.secret_key.get_secret_value().encode("utf-8")
    ).digest()
    keks = {1: derived}
    _kek_cache, _active_version_cache, _active_is_derived_cache = keks, 1, True
    return keks, 1, True


def _active_kek() -> tuple[int, bytes]:
    keks, active, _ = _load_keks()
    return active, keks[active]


def _kek_for_version(version: int) -> bytes:
    keks, _, _ = _load_keks()
    try:
        return keks[version]
    except KeyError as exc:
        raise RuntimeError(
            f"No BYOK KEK for version {version}; cannot decrypt a secret "
            "wrapped under a retired key version."
        ) from exc


def _gcm_seal(key: bytes, plaintext: bytes) -> bytes:
    nonce = os.urandom(_NONCE_LEN)
    return nonce + AESGCM(key).encrypt(nonce, plaintext, None)


def _gcm_open(key: bytes, blob: bytes) -> bytes:
    nonce, ct = blob[:_NONCE_LEN], blob[_NONCE_LEN:]
    # AESGCM.decrypt raises cryptography.exceptions.InvalidTag on any tamper.
    return AESGCM(key).decrypt(nonce, ct, None)


def encrypt(plaintext: bytes) -> bytes:
    """Envelope-encrypt ``plaintext`` and return one opaque blob.

    Fresh random DEK + nonces every call, so two encryptions of the same
    input differ. The blob's header records the active KEK version so
    ``decrypt`` can resolve the right wrapping key after a rotation.
    """
    if not isinstance(plaintext, (bytes, bytearray)):
        raise TypeError("encrypt expects bytes")
    kek_version, kek = _active_kek()
    dek = AESGCM.generate_key(bit_length=256)
    enc_key = _gcm_seal(dek, bytes(plaintext))
    enc_data_key = _gcm_seal(kek, dek)
    return _HEADER.pack(_MAGIC, kek_version, len(enc_data_key)) + enc_data_key + enc_key


def _split(blob: bytes) -> tuple[int, bytes, bytes]:
    if len(blob) < _HEADER.size:
        raise ValueError("ciphertext blob too short / malformed")
    magic, kek_version, edk_len = _HEADER.unpack(blob[: _HEADER.size])
    if magic != _MAGIC:
        raise ValueError("ciphertext blob has an unrecognized header")
    body = blob[_HEADER.size :]
    if len(body) < edk_len:
        raise ValueError("ciphertext blob truncated")
    enc_data_key = body[:edk_len]
    enc_key = body[edk_len:]
    return kek_version, enc_data_key, enc_key


def decrypt(blob: bytes) -> bytes:
    """Decrypt a blob produced by :func:`encrypt`.

    Resolves the wrapping KEK by the version in the header (multi-version
    support), unwraps the DEK, then decrypts the payload. Any tamper —
    header, wrapped DEK, or ciphertext — surfaces as
    ``cryptography.exceptions.InvalidTag``.
    """
    kek_version, enc_data_key, enc_key = _split(blob)
    kek = _kek_for_version(kek_version)
    dek = _gcm_open(kek, enc_data_key)
    return _gcm_open(dek, enc_key)


def rotate_secret(blob: bytes) -> bytes:
    """Re-wrap ``blob``'s DEK under the *active* KEK version.

    Decrypts the wrapped DEK with its stored version's KEK and re-wraps it
    under the current active KEK — the inner ``enc_key`` (the encrypted
    plaintext) is preserved byte-for-byte. Never touches the plaintext
    (FR-BYOK-12). Idempotent: rotating a blob already on the active version
    produces an equivalent blob (a fresh nonce on the wrapped DEK, same
    plaintext).
    """
    old_version, enc_data_key, enc_key = _split(blob)
    old_kek = _kek_for_version(old_version)
    dek = _gcm_open(old_kek, enc_data_key)  # unwrap (raises InvalidTag on tamper)
    new_version, new_kek = _active_kek()
    new_enc_data_key = _gcm_seal(new_kek, dek)
    return _HEADER.pack(_MAGIC, new_version, len(new_enc_data_key)) + new_enc_data_key + enc_key


def key_fingerprint(plaintext: bytes | str) -> str:
    """SHA-256 hex of the plaintext, for dedupe/idempotency (FR-BYOK-08).

    Not reversible; safe to store and compare. Never the key itself.
    """
    data = plaintext.encode("utf-8") if isinstance(plaintext, str) else bytes(plaintext)
    return hashlib.sha256(data).hexdigest()


def last4(plaintext: bytes | str) -> str:
    """Last 4 chars of the secret for masked display, or ``****`` if too short."""
    text = (
        plaintext.decode("utf-8", "replace")
        if isinstance(plaintext, (bytes, bytearray))
        else plaintext
    )
    return text[-4:] if len(text) >= 4 else "****"
