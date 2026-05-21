"""Presigned uploads to S3-compatible storage."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.core.config import get_settings
from app.core.errors import ValidationAppError
from app.core.ids import new_id

if TYPE_CHECKING:
    from app.models.user import User

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
    },
    "cover": {"image/png", "image/jpeg", "image/webp"},
    "attachment": {"*"},
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


def _client() -> "boto3.client":  # type: ignore[name-defined]
    s = get_settings()
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
    allowed = ALLOWED_PER_KIND[kind]
    if "*" not in allowed and content_type not in allowed:
        raise ValidationAppError(
            "Content-Type not allowed for this kind", code="upload.content_type",
            details={"allowed": sorted(allowed)},
        )
    if size_bytes > MAX_BYTES_PER_KIND[kind]:
        raise ValidationAppError("File too large", code="upload.too_large")

    s = get_settings()
    today = datetime.now(timezone.utc).strftime("%Y/%m/%d")
    key = f"{kind}/{user.id}/{today}/{new_id()}/{_safe_filename(filename)}"
    client = _client()

    try:
        url = client.generate_presigned_url(
            ClientMethod="put_object",
            Params={
                "Bucket": s.s3_bucket,
                "Key": key,
                "ContentType": content_type,
            },
            ExpiresIn=s.s3_presign_ttl_seconds,
            HttpMethod="PUT",
        )
    except ClientError as exc:  # pragma: no cover - network in dev
        raise ValidationAppError("Failed to sign upload", code="upload.sign_failed") from exc

    public_url = f"{s.s3_public_base_url.rstrip('/')}/{s.s3_bucket}/{key}"
    return {
        "url": url,
        "key": key,
        "headers": {"Content-Type": content_type},
        "expires_in": s.s3_presign_ttl_seconds,
        "public_url": public_url,
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
        try:
            client.create_bucket(Bucket=s.s3_bucket)
        except ClientError:  # pragma: no cover - best effort
            pass
