# Runbook: BYOK master key (KEK) rotation

S5.14 / ADR-0027 §2 / FR-BYOK-12 / R-S2. Rotates the server **KEK** that
wraps each user credential's per-secret DEK. Envelope encryption means
rotation re-wraps only the (small) wrapped-DEK — the encrypted plaintext key
blob is never touched, decrypted to the operator, or logged.

## Why envelope rotation is cheap

Each `user_llm_credentials` row stores an opaque `enc_blob`:

```
MAGIC | kek_version | enc_data_key (DEK wrapped under KEK vN) | enc_key (API key under DEK)
```

Rotation unwraps `enc_data_key` with the KEK version stamped in the header,
re-wraps the DEK under the new active KEK, and rewrites the header version.
`enc_key` (the encrypted plaintext key) is copied byte-for-byte. The
plaintext API key is never materialized.

## Preconditions (R-S2 — do these IN ORDER)

1. **Generate the new KEK** (32 random bytes, base64):
   ```
   python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"
   ```
2. **Deploy the new version alongside the old one** to EVERY API + worker
   process. `BYOK_MASTER_KEYS` must contain BOTH versions; do NOT remove the
   old one yet:
   ```
   BYOK_MASTER_KEYS={"1":"<old b64>","2":"<new b64>"}
   BYOK_MASTER_KEY_VERSION=2
   ```
   Roll the fleet and confirm every process booted (the KEK boot guard,
   `prod_guards.assert_byok_kek_present`, fires on API lifespan AND on the
   Celery `worker_process_init` — a missing/mismatched KEK aborts boot).
3. **Verify** old credentials still decrypt under v1 while new writes stamp v2
   (a smoke validate against a known credential is enough).

## Rotation

Run the CLI once the fleet carries both versions:

```
make shell.api   # or exec into the API/worker container
python -m app.cli rotate-byok-master-key
```

It batches over all credentials, re-wrapping any row not already on the
active version, commits per batch, and emits a single
`byok.master_key_rotated` audit event with `{rotated, skipped, to_version}`
(counts only — never key material). It is **idempotent**: rows already on the
active version are skipped; a re-run after a partial failure resumes safely.

## After rotation

1. Confirm `rotated` matches the credential count and `skipped` is the
   already-current remainder.
2. **Retain the old KEK version** in `BYOK_MASTER_KEYS` until you are certain
   no in-flight streamed turn still references it (a long-running streamed
   tutor turn decrypts under the version it resolved at start). Wait at least
   one max-turn-duration window, then remove the old version:
   ```
   BYOK_MASTER_KEYS={"2":"<new b64>"}
   BYOK_MASTER_KEY_VERSION=2
   ```
   and roll the fleet again.

## Hazards

- **Removing the old version too early** strands any credential not yet
  rotated (and any mid-flight turn) — `secrets_crypto` raises `RuntimeError`
  ("No BYOK KEK for version N") on decrypt. Always rotate fully BEFORE pruning
  the old version.
- **Rotating before the new version is fleet-wide** means a process without
  the new KEK can't decrypt freshly-rotated rows. Steps 2→3 gate this.
- The CLI never prints or logs plaintext keys or DEKs.
