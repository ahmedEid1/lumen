# ADR-0031: Notifications lifecycle — delete, clear, paging, retention

- **Status:** Accepted
- **Date:** 2026-06-07
- **Deciders:** @ahmedEid1 (via autonomous notifications feature-completeness batch)

## Context

Through 2.0.0 the notifications feature was a read-only viewer: a bell
popover over a bare newest-50 list with mark-read/mark-all-read, per-kind
dispatch prefs, and a daily digest. There was **no way to delete or clear a
notification, no path to history past the newest 50, no cheap badge count,
no mark-unread**, and the table grew without bound (the only purge was the
FK CASCADE on user deletion). A five-lens critique (product-UX, user
stories, backend API, frontend a11y, data lifecycle) plus a Codex pass
converged on the same P1 set; this ADR records the decisions that shaped
the build.

## Decision

1. **Hard delete, no `deleted_at`.** Notifications are ephemeral
   observability, not user-visible content — CLAUDE.md reserves
   soft-delete for Course/Lesson/Review. `DELETE /me/notifications/{id}`
   is a single ownership-gated statement (rowcount 0 → 404
   `notification.not_found`, indistinguishable for missing vs foreign).
2. **`security.*` rows are deletable like any other.** The
   `auth.refresh_reuse` path writes a durable audit row *before* the
   notification fan-out; the bell row is a heads-up, the audit log is the
   system of record. A test pins this so a future change is deliberate.
3. **Bulk clear defaults to the read subset.** `POST /clear
   {scope: 'read'|'all'}` — one DELETE statement. The UI only exposes
   "Clear read" (behind a confirm dialog); `'all'` exists in the API as an
   explicit opt-in but gets no one-tap button (a bulk action must not
   destroy unread/actionable items by default).
4. **History is cursor-paged on a NEW endpoint.** `GET /inbox` returns the
   existing `Cursor[T]` envelope, keyset `(created_at DESC, id DESC)` with
   the id tiebreaker (admin-reports idiom) — stable under `notify_admins`
   burst inserts that share a `created_at`. The bare `GET ""` newest-50
   array is **shape-frozen** for the bell and existing client code.
   A foreign/vanished cursor anchor degrades to the first page (no
   cross-user keyset oracle).
5. **The badge polls a COUNT.** `GET /unread-count` (typed
   `{unread_count}`) backed by a partial index
   `ix_notifications_user_unread (user_id) WHERE read_at IS NULL` (0053).
   This is *not* a return of the `(user_id, read_at)` index 0008 dropped —
   back then nothing filtered on `read_at`; now two predicates do, and the
   partial form indexes only unread rows. The bell polls the count every
   60s and fetches the full list only while open.
6. **Read state is two-way.** `POST /{id}/unread` clears `read_at` and
   deliberately does NOT touch `digested_at` — a row the digest already
   emailed stays out of the next digest after re-unread (no
   double-delivery).
7. **Retention closes the lifecycle.** A daily beat task
   (`notifications_prune`, 03:30 UTC) hard-deletes **read** rows older
   than `NOTIFICATION_RETENTION_DAYS` (default 90). Unread rows are never
   pruned. Digest-pending rows are unread by definition, so the prune
   cannot race the 07:00 digest.
8. **Digest stamps via statement-level UPDATE.** A user can now delete a
   row between the digest's SELECT and its `digested_at` stamp; an ORM
   flush over a vanished row raises `StaleDataError`, a statement UPDATE
   no-ops. Last writer wins; both paths stay best-effort, no
   cross-transaction locking.
9. **Frontend.** Shared `NotificationRow` (bell + `/notifications` page):
   a real `<button>`/non-interactive `<div>` plus a SIBLING kebab menu —
   no nested-interactive a11y violations; optimistic mutations across all
   three caches (bare list, count, both inbox filters) with rollback;
   per-kind icons (warning tone for `security.*`/`account.*`); SR live
   region announces new arrivals. Single-row delete ships **without** the
   delayed-network undo toast the critique proposed — the kebab is already
   a two-step deliberate action, and deferring the DELETE until toast
   expiry adds unmount/multi-delete edge cases disproportionate to the
   risk. Bulk clear keeps the confirm dialog.

## Alternatives considered

- **Soft-delete with `deleted_at`** — rejected: conventions reserve it for
  content; nothing needs notification undelete.
- **Offset paging via `Page[T]`** — rejected: CLAUDE.md says cursor for
  message/audit-style feeds; offset pages drift under concurrent inserts.
- **Evolving `GET ""` into an envelope** — rejected: breaking change to
  the bell + generated types for no user-visible gain; additive endpoint
  is strictly safer.
- **Delete-protect `security.*`** — rejected after verifying the durable
  audit row; protection would special-case delete, clear, AND prune.
- **Undo-toast with delayed DELETE** — rejected (see Decision 9).
- **WebSocket/SSE push** — descoped: 60s count poll is proportionate for
  this product; revisit only with a real-time product need.

## Consequences

- The notifications table is now bounded (clear + retention) and every
  row older than the newest 50 is reachable (inbox page).
- Badge cost per poll drops from 50 hydrated rows to one indexed COUNT.
- `digest_daily` rows deleted by the user before 07:00 are simply never
  emailed — accepted and documented (the in-app row was the source of
  truth, and the user explicitly discarded it).
- OpenAPI grew five operations. The frontend types stay hand-written
  (`types.ts` is hand-edited per DR-5 — `make api-client` would clobber
  the curated domain types; the new endpoints carry inline response
  types in `endpoints.ts` + `lib/notifications.ts`, the existing house
  pattern).

## References

- Spec synthesis: 5-lens critique workflow + Codex pass, 2026-06-07.
- ADR-0026 (visibility), migration 0008 (index swap), 0053 (partial index).
- `tests/test_notifications_manage.py` — pins every decision above.
