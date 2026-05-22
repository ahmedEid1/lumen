# Agent traces — learner + instructor "show your work" surfaces

Lumen v2 Phase I4. Two browser-facing trace surfaces that surface what
the multi-agent tutor (I2) and the self-critique authoring pipeline
(I3) are doing under the hood, scoped to the data the caller is
entitled to see.

The corresponding admin-facing surface
(`/admin/observability/llm-calls/{call_id}/trace`) is documented in
[architecture.md](architecture.md) and lives under H7. I4 is the
non-admin slice of the same machinery.

---

## What the learner sees

A learner asks the tutor a question. The orchestrator runs a planner,
dispatches sub-agents (retriever, web searcher, code runner,
quiz generator, concept explainer), optionally re-plans, then
synthesises the answer. Every step is recorded in the
`agent_traces` + `retrieval_audits` + `llm_calls` tables.

Underneath each assistant turn in the tutor panel, the
`AgentReasoningPanel` already shows a compact inline view of the
plan + tool calls + confidence. **New in I4**: that panel now ends
with a `See the full trace →` link that drops the learner into a
dedicated drill-down page.

### The drill-down page

URL: `/dashboard/tutor/{conversation_id}/turn/{message_id}`

Layout, top to bottom:

1. **Header.** Breadcrumb back to the dashboard, the message id and
   conversation id in mono / tabular-nums, and a step count.
2. **`CostBadge`.** A single chip carrying:
   - Total cost (USD, six fractional digits — sub-cent resolution).
   - Total wall-clock latency (ms; renders as seconds over 1000ms).
   - Total tokens used (prompt + completion summed).
   - Confidence (0–5, lime-accented at 4+).
   - Step count.
3. **Underlying LLM call.** Provider / model / per-call token + latency
   breakdown for the synthesiser call — the one whose output became
   the assistant's answer.
4. **`TraceTimeline`.** A vertical, collapsible timeline. Each row is
   a `TraceStepCard`:
   - Plan step — the planner's tool-call list + confidence.
   - Tool-call steps — name, rationale, args.
   - Sub-agent rows — retriever expands its chunks via
     `RetrievalChunkList`; web searcher shows snippets; code runner
     shows stdout.
   - Synthesis step — answer head + citation count.
   - The first row is pre-expanded so a recruiter loading the page
     gets a clear first read without clicking.
5. **Retrieval audits.** The chunks the retriever returned with their
   cosine-distance scores in `font-mono tabular-nums`. This is the
   literal RAG receipt: "this is the lesson text that grounded the
   answer."

### Auth posture

The endpoint
`GET /api/v1/me/tutor/conversations/{conversation_id}/turns/{message_id}/trace`
enforces:

- **404** when the conversation doesn't exist.
- **403** when it exists but is owned by someone else (we deliberately
  don't collapse to 404 — a learner sharing a trace URL with a
  friend should see "not yours" rather than "doesn't exist").
- **404** when the message doesn't belong to the conversation.
- **404** when the message id points at a user turn (no trace exists
  for user turns; the orchestrator hasn't run yet at that point).
- **200** with `{message_id, conversation_id, llm_call, agent_traces,
  retrieval_audits, total_cost_usd, total_latency_ms, total_tokens,
  confidence, created_at}` for the rightful owner.

### Heuristic: how the trace links to the turn

Today the I2 orchestrator does NOT carry the persisted
`tutor_messages.id` into the trace row (the message is persisted
after the orchestrator runs, and `call_logged` doesn't yet return
the `llm_calls.id` either — both are documented gaps in
`apps/backend/app/services/tutor_orchestrator.py`).

I4 therefore reconstructs the link **temporally**: every
`agent_traces` / `llm_calls` / `retrieval_audits` row whose
`user_id` matches the learner AND whose `created_at` falls in the
**120-second window** ending at the assistant message's
`created_at`. The window is generous (H7's audit-join window is
60s) because a complex multi-agent turn — planner + retriever +
re-plan + web search + synth — can sit close to a minute. We'd
rather over-pull a stray sibling than under-pull and produce an
empty timeline.

When the orchestrator later adds a `parent_message_id` column
(noted as a TODO in `tutor_orchestrator.py`), this service swaps
the temporal window for an exact FK lookup with no API surface
change.

---

## What the instructor sees

An instructor runs the self-critique authoring pipeline (Phase I3) on
a brief. The orchestrator runs researcher → outliner → critic ↺
reviser → lesson_drafter → final_critic. Every step is recorded in
`course_draft_traces`.

I3 already ships the per-draft timeline at `/studio/draft/{course_id}`
— a vertical list of steps with each row's prompt / response /
critic-scores / weak-spots / revision number visible on disclosure.

**New in I4**: a *replay* surface that lays out the same data as a
play-by-play, advancing 1.5 seconds per step, pausable, with a scrub
bar.

### The replay page

URL: `/studio/draft/{course_id}/replay`

Same data as the timeline but presented as:

1. Header with breadcrumb back to the trace timeline + course title +
   step count.
2. `CostBadge` (relabelled "Replay totals") showing the total
   wall-clock duration + step count.
3. `TraceTimeline` mounted in `autoPlay` mode:
   - The active step renders with a lime accent and is forced
     expanded. Non-active steps stay collapsed.
   - Auto-advance fires every 1500ms by default.
   - A control bar above the timeline carries play/pause, restart,
     step-back, step-forward buttons, plus a scrub slider and a
     position label ("step 2 / 7").
   - Pausing freezes the active step at the current index. Clicking
     a step's header in pause mode toggles its disclosure manually.
4. End-of-replay actions:
   - **Accept & publish** — flips the course to `published`.
   - **Revise this myself** — opens `/studio/{course_id}` for manual
     editing.
   - **Restart replay** — resets to step 0 and refetches.

### Auth posture

The endpoint
`GET /api/v1/me/studio/drafts/{course_id}/replay`
enforces:

- **401** when the caller is anonymous.
- **404** when the course doesn't exist (we don't leak whether a
  private slug exists).
- **403** when the caller is neither the course owner nor an admin.
  Same posture as the I3 timeline endpoint: a trace reveals the
  instructor's drafting approach, so we don't surface it to peer
  instructors.
- **200** with `{course_id, draft_id, steps, step_count,
  total_duration_ms}` for the rightful owner or admin.

---

## Operator notes

### Retention policy

Agent-trace rows live as long as their parent LLM call row. The
foreign key on `agent_traces.parent_call_id` is `ON DELETE SET
NULL`, so if an admin ever prunes `llm_calls` (cost-spike cleanup
etc.) the trace history is preserved — the forensic trail outlives
the cost meter row. Conversely, `agent_traces.parent_trace_id` is
`ON DELETE CASCADE` — pruning a root trace takes its whole subtree
with it.

`tutor_conversations` cascade-delete their `tutor_messages` rows
(GDPR-shaped — when a learner deletes a conversation the entire
transcript goes with it). The `agent_traces` rows for that
conversation are *not* directly linked to the conversation today
(temporal heuristic; see above), so they survive a conversation
delete. The deleted conversation's traces are still
attributable to the user via `user_id`; we rely on the
user-deletion cascade (`agent_traces.user_id` is just a String, no
FK) being driven by an explicit admin operation when a user is
removed for GDPR reasons.

`course_draft_traces.course_id` is `ON DELETE SET NULL` — deleting
a course preserves the trace history. `course_draft_traces.user_id`
is `ON DELETE CASCADE` against `users.id`, so a user removal does
take their authoring traces with them.

### Privacy

Trace payloads include:

- Prompts and response summaries (the first ~240 chars of each
  side of the round-trip). Both are partly user-generated content
  — the learner's question lands in the planner's prompt; the
  instructor's brief lands in the researcher's prompt.
- Retrieval audit chunks (which are course content, owned by the
  course's instructor and visible to enrolled learners).
- Cost, latency, token counts (system-generated, not sensitive).

We don't store *full* prompts or responses in the trace payload —
the orchestrator deliberately truncates to short heads. The full
prompt/response transcripts are also not in `llm_calls` (cost
meter only). If a vendor's API response carried a moderation flag
or a refusal, that lives in the `agent_traces` payload but not in
a row that's directly user-reachable; the learner sees the
synthesiser's user-facing refusal sentence instead.

### Where the data comes from

| Table | Writer | Reader (I4) |
|-------|--------|------------|
| `agent_traces` | I2 orchestrator (`tutor_orchestrator.orchestrate`) | `learner_traces.fetch_tutor_turn_trace` |
| `llm_calls` | H1 cost meter (`llm_call_log.call_logged`) | both endpoints |
| `retrieval_audits` | I2 retriever sub-agent (`tutor_subagents.run_retriever`) + I3 authoring researcher | tutor-turn endpoint |
| `course_draft_traces` | I3 orchestrator (`authoring_orchestrator.draft_course`) | replay endpoint |

The replay endpoint reuses I3's `list_traces_for_course` directly
so the "latest draft" selection logic stays in one place.

### Where the surface lives in the code

- Backend service: `apps/backend/app/services/learner_traces.py`
- Backend API: `apps/backend/app/api/v1/learner_traces.py` (NOT
  registered in `app/api/router.py` — orchestrator step mounts
  it under `/api/v1`).
- Backend schemas: `apps/backend/app/schemas/learner_traces.py`.
- Frontend pages:
  `apps/frontend/src/app/dashboard/tutor/[conversationId]/turn/[messageId]/page.tsx`,
  `apps/frontend/src/app/studio/draft/[courseId]/replay/page.tsx`.
- Frontend shared components: `apps/frontend/src/components/trace/`
  (`TraceTimeline`, `TraceStepCard`, `RetrievalChunkList`,
  `CostBadge`).
- "See the full trace" link: `apps/frontend/src/components/tutor/agent-reasoning-panel.tsx`
  (additive — the I2 panel keeps its existing inline view).
