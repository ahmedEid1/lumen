"""Ed25519 keypair + JCS signing helpers for Open Badges 3.0 credentials.

The OB3 spec (§8 "Proofs") allows a few cryptographic suites; we
implement *EdDSA + JCS-2022*: take the credential JSON minus its
``proof`` member, serialize it deterministically (RFC 8785-style: keys
sorted, no whitespace, all-Unicode strings), sign those bytes with
Ed25519, and embed the signature as base64url on a ``proof`` object.
This is the simplest path that produces a credential a generic VC
verifier (or another Lumen instance) can check without any
URDNA2015 / RDF canonicalization machinery — which is why ``pyld``
sits in the dependency list but is only wired up here for later
``did:web`` work.

Dev / test mode never requires the operator to mint a key: when
``settings.badges_signing_key`` is empty we derive a deterministic
Ed25519 seed from ``settings.secret_key`` so the same dev env always
produces the same verifier output. Production refuses to boot if
``secret_key`` is still the dev default (see
:meth:`Settings.assert_production_ready`) so this fallback can't be
mistaken for prod posture.
"""

from __future__ import annotations

import base64
import hashlib
import json
from functools import lru_cache
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from app.core.config import get_settings


def _b64u(data: bytes) -> str:
    """URL-safe base64 with no padding — the multibase / JWS convention."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64u_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


@lru_cache(maxsize=1)
def _load_private_key() -> ed25519.Ed25519PrivateKey:
    """Load the Ed25519 signing key, falling back to a derived dev key.

    Cached because settings rarely change between requests, and a hot
    handler should not re-derive an Ed25519 seed per credential.
    Tests that flip env vars call :func:`reset_for_tests` to clear it.
    """
    s = get_settings()
    raw = s.badges_signing_key.get_secret_value()
    if raw.strip():
        # Operator-provided PEM. Accept the standard PKCS#8 unencrypted
        # form produced by ``openssl genpkey -algorithm ed25519``.
        key = serialization.load_pem_private_key(raw.encode("utf-8"), password=None)
        if not isinstance(key, ed25519.Ed25519PrivateKey):
            raise RuntimeError(
                "BADGES_SIGNING_KEY must be an Ed25519 private key in PEM form"
            )
        return key
    # Dev / test fallback: derive a stable seed from the app secret.
    # Domain-separate the hash so the seed can't be confused with any
    # other key material that also feeds off ``secret_key``.
    seed = hashlib.sha256(
        b"lumen.badges.ed25519.v1:" + s.secret_key.get_secret_value().encode("utf-8")
    ).digest()
    return ed25519.Ed25519PrivateKey.from_private_bytes(seed)


def reset_for_tests() -> None:
    """Clear the cached key so tests can flip ``badges_signing_key`` mid-run."""
    _load_private_key.cache_clear()


def public_key_multibase() -> str:
    """The issuer's public key, encoded as the ``z``-prefixed multibase
    form OB3 verifiers consume (multicodec 0xED 0x01 for Ed25519, then
    base58btc — but we ship the simpler base64url variant under the
    same ``z``-prefix convention because the verify endpoint is the
    only consumer in v1 and it speaks our exact format).
    """
    pub = _load_private_key().public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return "z" + _b64u(pub)


def _jcs_canonicalize(obj: Any) -> bytes:
    """Deterministic JSON serialization for signing.

    Not the full RFC 8785 (we don't normalize numbers because every
    value we sign is a string, integer, bool, or container — never a
    float — so the difference is moot). Sorted keys + no whitespace +
    ``ensure_ascii=False`` is enough for two implementations of this
    same module to agree byte-for-byte.
    """
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sign_credential(credential: dict[str, Any]) -> dict[str, Any]:
    """Return ``credential`` augmented with a ``proof`` object.

    Convention:
      * ``type``  — ``"DataIntegrityProof"`` (the W3C VC 2.0 generic
        wrapper, vs. the older ``Ed25519Signature2020``)
      * ``cryptosuite`` — ``"eddsa-jcs-2022"`` per OB3 §8.2
      * ``created`` — the credential's ``validFrom`` if present, else
        the current value of ``issuanceDate``; the caller already
        sets one of those so we don't recompute here
      * ``verificationMethod`` — issuer URL + a stable key ID fragment
        so a verifier can fetch the issuer profile and match keys
      * ``proofPurpose`` — ``"assertionMethod"`` (this is a learner
        assertion, not authentication or delegation)
      * ``proofValue`` — base64url Ed25519 signature, ``z``-prefixed

    The input credential MUST NOT already contain a ``proof`` member;
    if it does we drop it before re-signing so re-issue is idempotent.
    """
    payload = {k: v for k, v in credential.items() if k != "proof"}
    msg = _jcs_canonicalize(payload)
    sig = _load_private_key().sign(msg)
    s = get_settings()
    proof = {
        "type": "DataIntegrityProof",
        "cryptosuite": "eddsa-jcs-2022",
        "created": payload.get("validFrom") or payload.get("issuanceDate"),
        "verificationMethod": f"{str(s.badges_issuer_url).rstrip('/')}#lumen-badges-key-1",
        "proofPurpose": "assertionMethod",
        "proofValue": "z" + _b64u(sig),
    }
    # Stable ordering of the outer object so what we return matches
    # what verify_credential will canonicalize on the receive side.
    out = dict(payload)
    out["proof"] = proof
    return out


def verify_credential(credential: dict[str, Any]) -> bool:
    """Re-canonicalize the credential and check its Ed25519 signature.

    Returns ``False`` on any structural problem (missing proof,
    malformed proofValue, wrong cryptosuite) — verifiers should not
    expose the *reason* a tampered credential failed because that
    leaks oracle bits.
    """
    proof = credential.get("proof")
    if not isinstance(proof, dict):
        return False
    if proof.get("type") != "DataIntegrityProof":
        return False
    if proof.get("cryptosuite") != "eddsa-jcs-2022":
        return False
    raw = proof.get("proofValue", "")
    if not isinstance(raw, str) or not raw.startswith("z"):
        return False
    try:
        sig = _b64u_decode(raw[1:])
    except (ValueError, base64.binascii.Error):
        return False

    payload = {k: v for k, v in credential.items() if k != "proof"}
    msg = _jcs_canonicalize(payload)
    pub = _load_private_key().public_key()
    try:
        pub.verify(sig, msg)
    except Exception:
        # cryptography raises ``InvalidSignature`` here, but downstream
        # callers only care about pass/fail — collapse to a bool.
        return False
    return True
