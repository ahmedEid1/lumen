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
        config=Config(signature_version="s3v4", s3={"addressing_style": "path" if s.s3_force_path_style else "auto"}),
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
        raise ValidationAppError(
            "Content-Type not allowed", code="upload.content_type_denied"
        )
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


def ensure_bucket() -> None:
    s = get_settings()
    client = _client()
    try:
        client.head_bucket(Bucket=s.s3_bucket)
    except ClientError:
        with contextlib.suppress(ClientError):  # pragma: no cover - best effort
            client.create_bucket(Bucket=s.s3_bucket)
