# ADR-0005: Presigned uploads direct to object storage

- **Status:** Accepted
- **Date:** 2026-05-21
- **Deciders:** @ahmedEid1

## Context

Lesson content can include video and large files. Streaming uploads through the API process would:

- Block uvicorn workers on slow client networks.
- Waste bandwidth (FE → API → S3 instead of FE → S3 directly).
- Force us to scale the API for upload throughput, not request rate.

## Decision

Use presigned PUT URLs:

1. FE asks `POST /api/v1/uploads/sign` with `{filename, content_type, kind}`.
2. API verifies the user can upload, computes the object key (`{kind}/{user_id}/{ulid}/{filename}`), returns `{url, method, headers, key, expires_in}`.
3. FE uploads bytes via `PUT url` to MinIO/S3 directly.
4. FE posts the key back as part of the entity create/update request.
5. API verifies the object exists (`HEAD`), records `assets` row, kicks off a Celery task for derivatives.

## Alternatives considered

- **TUS resumable** — better UX for very large files; we can add later behind the same `services/uploads.py` interface.
- **Server-side multipart proxy** — simplest, but defeats the purpose.

## Consequences

- Object storage must be reachable from the browser (CORS on the bucket).
- We need a sweep task to delete unreferenced assets older than 24 h (signed but never claimed).
- MIME / size validation happens both client-side (UX) and server-side (security) via probe before claim.

## References

- [Boto3 generate_presigned_url](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/s3-presigned-urls.html)
