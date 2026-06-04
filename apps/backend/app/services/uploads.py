"""Presigned uploads to S3-compatible storage."""

from __future__ import annotations

import contextlib
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.core.config import get_settings
from app.core.errors import ValidationAppError
from app.core.ids import new_id

if TYPE_CHECKING:
    from app.models.user import User

# Types we refuse for every kind because S3 serves uploaded blobs at the
# Content-Type the client picked, and the bucket is publicly readable —
# image/svg+xml carries <script>, text/html *is* a script vector, and
# anything that renders/executes in a browser turns the public bucket
# into a hosted-phishing/XSS surface on the platform's own domain.
ALWAYS_DENIED_TYPES = frozenset(
    {
        "text/html",
        "text/xhtml+xml",
        "application/xhtml+xml",
        "image/svg+xml",
        "application/javascript",
        "application/x-javascript",
        "text/javascript",
    }
)

ALLOWED_PER_KIND = {
    "avatar": {"image/png", "image/jpeg", "image/webp"},
    "lesson": {
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/gif",
        "video/mp4",
        "video/webm",
        "application/pdf",
        "text/plain",
        "text/markdown",
        "application/zip",
        # WebVTT captions for video lessons. text/vtt is the
        # IANA-registered type. Some browsers also accept text/plain
        # for VTT, but the spec says text/vtt so we require it.
        "text/vtt",
    },
    "cover": {"image/png", "image/jpeg", "image/webp"},
    # Attachments used to wildcard ("*") — that let any authenticated
    # user PUT text/html or image/svg+xml to the public bucket, hosting
    # phishing/XSS pages on the platform's own origin. The list below is
    # the union of common doc/media/code-bundle types learners actually
    # attach. Anything novel should be added here explicitly.
    "attachment": {
        "application/pdf",
        "application/zip",
        "application/x-7z-compressed",
        "application/x-tar",
        "application/gzip",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.ms-excel",
        "application/vnd.ms-powerpoint",
        "application/json",
        "text/plain",
        "text/markdown",
        "text/csv",
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/gif",
        "video/mp4",
        "video/webm",
        "audio/mpeg",
        "audio/ogg",
        "audio/wav",
    },
}

MAX_BYTES_PER_KIND = {
    "avatar": 5 * 1024 * 1024,
    "lesson": 1024 * 1024 * 1024,  # 1 GB
    "cover": 10 * 1024 * 1024,
    "attachment": 100 * 1024 * 1024,
}

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_filename(name: str) -> str:
    cleaned = _SAFE.sub("-", name.strip())[:120]
    return cleaned or "file"


def _client(s=None):
    s = s or get_settings()
    return boto3.client(
        "s3",
        endpoint_url=s.s3_endpoint_url or None,
        aws_access_key_id=s.s3_access_key_id,
        aws_secret_access_key=s.s3_secret_access_key.get_secret_value(),
        region_name=s.s3_region,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path" if s.s3_force_path_style else "auto"},
        ),
    )


def sign_upload(
    *,
    user: User,
    filename: str,
    content_type: str,
    kind: str,
    size_bytes: int,
) -> dict[str, object]:
    if kind not in ALLOWED_PER_KIND:
        raise ValidationAppError("Unsupported upload kind", code="upload.kind")
    # Defense-in-depth: even if a future kind opens its allow-list, these
    # types are forever rejected because they execute / render in a
    # browser and the public bucket would happily serve them as-is.
    if content_type.lower() in ALWAYS_DENIED_TYPES:
        raise ValidationAppError("Content-Type not allowed", code="upload.content_type_denied")
    allowed = ALLOWED_PER_KIND[kind]
    if content_type not in allowed:
        raise ValidationAppError(
            "Content-Type not allowed for this kind",
            code="upload.content_type",
            details={"allowed": sorted(allowed)},
        )
    max_bytes = MAX_BYTES_PER_KIND[kind]
    if size_bytes > max_bytes:
        raise ValidationAppError("File too large", code="upload.too_large")

    s = get_settings()
    today = datetime.now(UTC).strftime("%Y/%m/%d")
    key = f"{kind}/{user.id}/{today}/{new_id()}/{_safe_filename(filename)}"
    client = _client(s)

    # Switched from generate_presigned_url(PUT) to generate_presigned_post
    # so we can attach a ``content-length-range`` policy condition. With
    # PUT, ``size_bytes`` was advisory — S3 didn't actually enforce the
    # cap — and a client could upload a 1GB file claiming 1KB. POST
    # presign returns a policy that S3 *does* enforce on the upload, so
    # the per-kind size cap is now hard.
    try:
        presigned = client.generate_presigned_post(
            Bucket=s.s3_bucket,
            Key=key,
            Fields={"Content-Type": content_type},
            Conditions=[
                {"Content-Type": content_type},
                ["content-length-range", 1, max_bytes],
            ],
            ExpiresIn=s.s3_presign_ttl_seconds,
        )
    except ClientError as exc:  # pragma: no cover - network in dev
        raise ValidationAppError("Failed to sign upload", code="upload.sign_failed") from exc

    public_url = f"{s.s3_public_base_url.rstrip('/')}/{s.s3_bucket}/{key}"
    return {
        "url": presigned["url"],
        # Client must POST multipart/form-data with these fields plus a
        # final ``file`` field containing the bytes. S3 verifies the
        # policy (content-length-range + Content-Type) against the
        # actual upload — so the cap is enforced server-side, not just
        # promised by the client.
        "fields": presigned["fields"],
        "key": key,
        "expires_in": s.s3_presign_ttl_seconds,
        "public_url": public_url,
        "max_bytes": max_bytes,
    }


def head(key: str) -> dict[str, object]:
    s = get_settings()
    client = _client()
    return client.head_object(Bucket=s.s3_bucket, Key=key)


# ---------------------------------------------------------------------------
# Clone asset re-homing — download → re-validate(bytes) → re-upload (DR-9).
#
# DR-9 SUPERSEDES ADR-0028's ``copy_object_validated``: boto3 ``CopyObject``
# never exposes the copied bytes to re-sniff, and R-S5 mandates re-validating
# the COPIED BYTES (a source whose stored content_type lies must be caught). So
# we ``get_object`` the bytes, re-run the upload-time validation surface
# (ALWAYS_DENIED_TYPES / ALLOWED_PER_KIND / MAX_BYTES_PER_KIND + a magic-byte
# sniff) on the FETCHED bytes — never trusting the source ``Asset`` row's stored
# type/size — then ``put_object`` under the cloner's namespace.
# ---------------------------------------------------------------------------


class AssetRevalidationError(Exception):
    """The fetched bytes fail the per-kind validation surface (R-S5).

    Carries a short ``reason`` so the clone audit can record WHY an object was
    not re-homed (denied type / disallowed-for-kind / too large). Best-effort:
    the worker strips the media ref and continues; the task never 500s.
    """

    def __init__(self, message: str, *, reason: str):
        super().__init__(message)
        self.reason = reason


#: Bytes sniffed from the head of a fetched object to detect the real type — a
#: source whose stored ``content_type`` lies (image/png header on a text/html
#: body) must be caught on the BYTES, not the metadata (R-S5). Small magic-byte
#: prefixes for the allowlisted media; anything unrecognized falls back to the
#: object's reported ``ContentType`` (still validated against the allowlist).
_MAGIC_PREFIXES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"%PDF-", "application/pdf"),
    (b"PK\x03\x04", "application/zip"),
    (b"<!DOCTYPE html", "text/html"),
    (b"<html", "text/html"),
    (b"<svg", "image/svg+xml"),
    (b"<?xml", "application/xml"),
)


def _sniff_content_type(head_bytes: bytes, *, reported: str) -> str:
    """Best-effort magic-byte sniff; falls back to the reported type.

    WEBP is ``RIFF....WEBP``; check the 4-byte tag at offset 8.
    """
    lowered = head_bytes.lstrip()[:32].lower()
    for prefix, ctype in _MAGIC_PREFIXES:
        if lowered.startswith(prefix.lower()):
            return ctype
    if head_bytes[:4] == b"RIFF" and head_bytes[8:12] == b"WEBP":
        return "image/webp"
    return reported


def download_revalidate_reupload(
    *,
    src_key: str,
    dst_kind: str,
    dst_owner_id: str,
    filename: str | None = None,
) -> dict[str, object]:
    """Re-home one in-bucket object into the cloner's namespace (DR-9 / R-S5).

    ``get_object`` the source bytes, magic-byte sniff + re-validate them against
    the per-kind allowlist (NOT the source ``Asset`` row's stored type), then
    ``put_object`` to ``{dst_kind}/{dst_owner_id}/{YYYY/MM/DD}/{new_id}/{name}``.
    Returns ``{key, public_url, content_type, size_bytes}``. Raises
    :class:`AssetRevalidationError` when the fetched bytes are a denied type /
    disallowed-for-kind / oversized — the caller records the failure and strips
    the ref (best-effort, FR-CLONE-13).
    """
    if dst_kind not in ALLOWED_PER_KIND:
        raise AssetRevalidationError(f"Unknown kind {dst_kind}", reason="unknown_kind")
    s = get_settings()
    client = _client(s)

    obj = client.get_object(Bucket=s.s3_bucket, Key=src_key)
    body = obj["Body"].read()
    size_bytes = len(body)
    reported = str(obj.get("ContentType") or "application/octet-stream")
    sniffed = _sniff_content_type(body[:64], reported=reported)

    # The effective type is the WORST of (reported, sniffed): if EITHER says a
    # denied/disallowed type, refuse — a lying header can't launder bytes.
    for candidate in (sniffed, reported):
        if candidate.lower() in ALWAYS_DENIED_TYPES:
            raise AssetRevalidationError(f"Denied type {candidate}", reason="denied_type")
    allowed = ALLOWED_PER_KIND[dst_kind]
    # Validate the SNIFFED type primarily (the bytes); reported is a fallback
    # only when the sniff is inconclusive (returned the reported type unchanged).
    effective = sniffed
    if effective not in allowed:
        raise AssetRevalidationError(
            f"Type {effective} not allowed for {dst_kind}", reason="type_not_allowed"
        )
    max_bytes = MAX_BYTES_PER_KIND[dst_kind]
    if size_bytes > max_bytes:
        raise AssetRevalidationError(
            f"Object {size_bytes}B exceeds {max_bytes}B", reason="too_large"
        )

    name = _safe_filename(filename or src_key.rsplit("/", 1)[-1])
    today = datetime.now(UTC).strftime("%Y/%m/%d")
    dst_key = f"{dst_kind}/{dst_owner_id}/{today}/{new_id()}/{name}"
    client.put_object(Bucket=s.s3_bucket, Key=dst_key, Body=body, ContentType=effective)
    public_url = f"{s.s3_public_base_url.rstrip('/')}/{s.s3_bucket}/{dst_key}"
    return {
        "key": dst_key,
        "public_url": public_url,
        "content_type": effective,
        "size_bytes": size_bytes,
    }


def is_bucket_url(url: str | None) -> bool:
    """True iff ``url`` points at our own public bucket (so it must be re-homed).

    External URLs (a third-party video host) are referenced as-is and never
    copied (FR-CLONE — "external URLs left as is").
    """
    if not url:
        return False
    s = get_settings()
    prefix = f"{s.s3_public_base_url.rstrip('/')}/{s.s3_bucket}/"
    return url.startswith(prefix)


def key_from_bucket_url(url: str) -> str:
    """Extract the S3 object key from one of our public bucket URLs."""
    s = get_settings()
    prefix = f"{s.s3_public_base_url.rstrip('/')}/{s.s3_bucket}/"
    return url[len(prefix) :]


def ensure_bucket() -> None:
    s = get_settings()
    client = _client()
    try:
        client.head_bucket(Bucket=s.s3_bucket)
    except ClientError:
        with contextlib.suppress(ClientError):  # pragma: no cover - best effort
            client.create_bucket(Bucket=s.s3_bucket)
