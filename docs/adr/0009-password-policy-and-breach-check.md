# ADR-0009: Password policy, single source of truth, and HIBP gate

- **Status:** Accepted
- **Date:** 2026-05
- **Deciders:** maintainers

## Context

The application has three endpoints that accept a *new* password:

- `POST /auth/register`
- `POST /auth/password-reset/confirm`
- `POST /users/me/change-password`

Pre-iter 39 each had its own validator. Only register enforced a
character-class check (`isalnum() and v.lower() == v` → reject), so a
user who signed up with `Password!1234` could downgrade to
`password12345` via either reset or change — bypassing the policy at
precisely the moments when an attacker is most likely to be acting
(holding a reset token, having hijacked a session).

The audit comment in `password_reset.py` from iter 39 also flagged
"HIBP / breach-list lookup is future work" — known-breached passwords
were silently accepted across all three paths.

## Decision

One module owns the policy: `app.schemas.auth.validate_password_strength`.
Wired to all three sites via Pydantic `field_validator`.

A second helper, `app.services.password_hibp.assert_not_pwned`, runs
the optional HIBP k-anonymity check (only the first 5 hex chars of
SHA-1 leave the process) and is called from the same three sites.

Operational properties of the HIBP gate:

- **Opt-in via `HIBP_ENABLED`**, defaults off. Fresh checkouts and
  CI runs do not perform third-party callouts. Enable in staging /
  prod.
- **Fail open.** Timeouts and 5xx responses from HIBP return False
  (allow). The structural strength check still applies. Refusing to
  let users register because a third-party API is slow would be its
  own outage.
- **Pad-aware.** HIBP returns padding rows (count=0) to defeat
  traffic analysis. Those must NOT trigger a false-positive
  "breached" verdict.

Future work — explicitly out of scope for this ADR:

- HIBP caching in Redis (lookups for `password123` would otherwise
  hit HIBP on every retry from a brute-forcer);
- length-variance constraint (24+ char passphrases without symbols
  could legitimately pass the current check).

## Alternatives considered

- **Length-only policy.** Rejected; many breached passwords are 12+
  chars (`password12345`, `iloveyou1234`). Length + class is the
  industry baseline.
- **Required complexity beyond mix-class** (must contain a digit
  AND a symbol AND mixed case). Rejected — pushes users toward
  L33t-substitutions which HIBP catches; better to lean on HIBP.

## Consequences

Positive:
- One place to tighten policy. Adding HIBP took zero schema changes.
- Reset / change cannot downgrade a registered password.

Negative:
- HIBP adds ~200 ms to register / reset / change when enabled. The
  fail-open default makes this a soft latency cost, not a reliability
  one.

## References

- iter 39 (`sec(auth): unify password strength policy`)
- iter 52 (`sec(auth): optional HIBP breach-list check`)
