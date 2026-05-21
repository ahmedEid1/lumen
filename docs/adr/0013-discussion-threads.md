# ADR-0013: Course discussion threads — flat-reply forum

- **Status:** Accepted
- **Date:** 2026-07
- **Deciders:** maintainers

## Context

Lumen ships flat real-time chat per course (iter 30 / chat WS) and
1-rating-per-learner reviews. Neither fits the "I'm stuck on lesson
5, can someone help?" use case:

- chat scrolls and isn't threadable; an answer 30 minutes later is
  lost in noise;
- reviews are a single rating + body per learner — they're not a
  conversation surface.

Without a third surface, the support load fell onto the course
chat (degrading its real-time feel) and instructor inboxes
(unbatched, ephemeral, no peer help).

## Decision

Two-table flat-reply discussion forum per course
(`discussions` + `discussion_replies`):

- **Thread**: title + body + author + `deleted_at`. Pinned to the
  course via `course_id` (FK cascade).
- **Reply**: body + author + `deleted_at`. Pinned to the thread.
  No nesting — replies are a flat list under the thread.

Visibility reuses `can_view_course` (ADR-0008): drafts hidden from
strangers, archived courses readable to enrolled learners. Posting
requires read access. Soft-delete is allowed for the author, the
course owner, or an admin.

Replies bump the parent's `updated_at`. The list endpoint sorts by
`max(thread.updated_at, last reply created_at)` desc so an active
thread surfaces, like every working forum since 2003.

Author of a thread gets a notification when someone (not them)
replies — `NotificationKind.discussion_reply` (iter 79).

## Why flat, not nested

Every modern Q&A forum has converged on Stack-Overflow-style
"answer + comments" semantics — flat at the answer level, no
reply-to-reply chains. The lessons from comment threads (Reddit,
Twitter, every news site comments section ever) is that:

1. unbounded nesting harms readability — past 3 levels the indent
   eats the screen and the discussion becomes unfollowable;
2. it encourages snipy back-and-forth instead of "answer the
   question, then leave a comment if you must";
3. it complicates moderation — deleting a parent strands a tree.

Flat replies sidestep all three. If a discussion truly needs a
sub-discussion, it should be its own thread.

## Alternatives considered

- **Build on top of chat** (long-lived messages with replies).
  Rejected — chat is real-time and ephemeral, mixing the two
  models would harm both. Chat's social loop is "who's online";
  forum's social loop is "I'll answer this in an hour."
- **Nested replies (Reddit-style)**. Rejected per "Why flat"
  above.
- **External Discourse / GitHub Discussions integration**.
  Rejected — auth model is bespoke (per-course enrollment gating
  for non-published), and shipping a third-party widget defeats
  the embedded-in-the-course UX.

## Consequences

Positive:
- One more pillar of the LMS feature set; reviews / chat / forum
  are now complementary surfaces.
- Notification feedback loop (iter 79) plus deep-linking from the
  bell (iter 80) closes the "did anyone answer me?" loop.

Negative:
- Two more tables; conftest truncate list grows. Acceptable.
- Soft-delete leaves rows in the DB until a future retention
  worker cleans them up (consistent with how chat / lessons /
  courses handle soft-delete).

## References

- iter 77 (`feat(discussions): course discussion threads`)
- iter 78 (`feat(discussions): UI pages and entry point`)
- iter 79 (`feat(discussions): notify thread author on new reply`)
- iter 80 (`feat(notifications): bell deep-links`)
- ADR-0008 (visibility predicates)
