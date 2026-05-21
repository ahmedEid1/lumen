# ADR-0008: Soft-delete and unpublished-course visibility rules

- **Status:** Accepted
- **Date:** 2026-04
- **Deciders:** maintainers

## Context

Courses can be in three states (`draft`, `published`, `archived`) and
are independently soft-deletable via `deleted_at`. Across iterations
22–47 we hardened a dozen endpoints that read or wrote courses in
inconsistent ways:

- some used `get_course` (which filters `deleted_at`) and silently
  404'd for enrolled learners whose course got archived (iter 24);
- some used the raw `course_id` lookup and exposed soft-deleted rows
  via subject tiles (iter 30), the dashboard (iter 26), or progress
  writes (iter 27);
- a few endpoints — duplicate (iter 46), bookmark add (iter 47) —
  loaded courses via `get_course` and then surfaced fields from
  *unpublished* courses, leaking draft titles / overviews / owner
  names based on whoever knew the course id.

Without a single authoritative answer, each new endpoint had to
re-derive the rule and tended to get it wrong.

## Decision

Two predicates, used everywhere:

1. **`courses_repo.get_course(id)`** filters `deleted_at IS NULL`.
   The default for any code path that just wants "a real course."
2. **`courses_service.can_view_course(db, course, viewer)`** is the
   authoritative *visibility* check. Returns True for:
   - published courses (anyone, including anonymous);
   - any status when the viewer is the owner or an admin;
   - non-published when the viewer has an enrollment (so iter-24
     archived/draft access for in-progress learners keeps working).

   Bookmark, duplicate, course detail, and the lesson player all
   gate on this predicate.

Soft-deleted rows are invisible to every read path **except certificate
download / verify** (iter 45) — a credential is a permanent record
and shouldn't be retracted by a curator's content cleanup. Cert
endpoints use `db.get(Course, id)` directly to bypass the filter.

For mutating writes against soft-deleted lessons (iter 27) we reject
with `lesson.not_found` instead of silently writing — the LessonProgress
row would be orphaned by the next cohort cleanup.

## Alternatives considered

- **One catch-all predicate that takes a "context" enum** (CATALOG,
  DETAIL, MUTATION). Rejected — context-specific rules ended up
  divergent enough that the enum branches dominated the function
  body; two named predicates are simpler to read at a callsite.
- **Hard-delete instead of soft-delete.** Rejected — losing enrollment
  history would break analytics and the cert-verification audit trail.

## Consequences

Positive:
- Every visibility-impacting endpoint that's been added or modified
  since iter 22 now uses one of the two predicates, so the rule is
  enforceable by review rather than memorisation.
- Cert resilience is explicit and tested (iters 44, 45) rather than
  accidental.

Negative:
- Two predicates rather than one means callers must pick correctly.
  The naming is meant to make the right pick obvious (`can_view_course`
  in any handler that returns course fields to a non-owner viewer;
  `get_course` everywhere else).

Operational:
- The `can_view_course` predicate runs an enrollment lookup on the
  non-published branch. For high-traffic public catalog endpoints
  the published branch short-circuits before any DB call.

## References

- iter 24 (`fix(courses): keep enrolled learners' access after archive`)
- iter 26 (`fix(dashboard): hide enrollments to soft-deleted courses`)
- iter 27 (`fix(progress): reject writes against soft-deleted lessons`)
- iter 28 (`fix(admin): subject delete with attached courses returns 409`)
- iter 30 (`fix(catalog): subject tiles ignore soft-deleted courses`)
- iter 44 (`fix(enrollment): refuse unenroll after completion`)
- iter 45 (`fix(cert): PDF download survives course soft-delete`)
- iter 46 (`sec(courses): duplicate refuses other instructors' drafts`)
- iter 47 (`sec(bookmarks): apply course visibility on add and list`)
