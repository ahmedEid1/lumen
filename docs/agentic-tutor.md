# Agentic tutor (Lumen v2 Phase I2)

Operator + developer guide to Lumen's multi-agent tutor. This is the
orchestration moat — the visible "agent thinking" that makes the
project legible to a recruiter in 60 seconds.

## What it does

When a learner asks the tutor a question, Lumen no longer fires a
single-shot RAG call. Instead the request flows through a
planner-orchestrator that picks one or more specialised sub-agents,
collects their outputs, and synthesises the final answer:

```
User question
    ↓
Planner LLM call → ToolPlan [(tool_name, args, rationale), ...]
    ↓
For each tool call (hard cap: 5 rounds per turn):
    ↓
    Sub-agent runs → structured ToolResult (Pydantic model)
    ↓
Optional re-plan LLM call → "do I need one more tool?"
    ↓
Synthesiser LLM call → final answer with [L:<lesson_id>] citations
```

Hard caps:

* **5 tool-call rounds per turn** (the orchestrator loop budget).
* **3 LLM round-trips per turn** (plan / re-plan / synthesise).

Every LLM call is metered via the H1 cost meter
(`call_logged(feature="tutor.multi_agent.<step>")`); every decision
step writes one row to `agent_traces` via `record_step`. The admin
observability page at `/admin/observability` renders the per-turn
tree end-to-end.

## The five sub-agents

| Sub-agent          | LLM call? | What it does                                         |
| ------------------ | --------- | ---------------------------------------------------- |
| `retriever`        | No        | RAG over `lesson_chunks` for the current course      |
| `web_searcher`     | No        | Tavily-backed open-web search                        |
| `code_runner`      | No        | Sandboxed Python (RestrictedPython, math/statistics) |
| `quiz_generator`   | Yes       | One MCQ practice question                            |
| `concept_explainer`| Yes       | "Explain this differently" re-phrasing               |

Each sub-agent:

* Returns a Pydantic model so the orchestrator can serialise its
  payload into the synthesiser's prompt.
* Writes one `agent_traces` row via `record_step` with
  `step="sub_agent.<name>"`, parented to the orchestrator's plan.
* Routes any LLM call through `call_logged(feature="tutor.subagent.<name>")`
  so the H1 dashboard rolls cost up by sub-agent.

## Sub-agent vocabulary

The planner prompt uses these tool names verbatim. The model is
told to emit JSON of shape:

```json
{
  "tool_calls": [
    {"tool_name": "retriever",
     "args": {"query": "..."},
     "rationale": "..."}
  ],
  "confidence_after_plan": 4,
  "final_answer_hint": null
}
```

Hard rules baked into the planner system prompt:

* `tool_calls` MUST be 1-3 items.
* `tool_name` is one of: `retriever`, `web_searcher`, `code_runner`,
  `quiz_generator`, `concept_explainer`.
* `confidence_after_plan` is the planner's 0-5 self-estimate.

On a malformed planner reply we fall back to a single-tool retriever
plan (Phase E1 behaviour) — the learner gets a clean answer even if
the planner LLM call failed or returned garbage.

## Environment variables

### `TAVILY_API_KEY` (optional)

Enables the `web_searcher` sub-agent. Tavily ships a free tier of
1000 searches/month at the time of writing — sufficient for tutor
use cases.

* If unset: the `web_searcher` sub-agent returns an empty result
  with `note="web search disabled (no TAVILY_API_KEY)"`. The
  orchestrator records the trace and the synthesiser falls back to
  the retriever's chunks. **This is graceful degradation by design.**
* If set: the sub-agent invokes `tavily.TavilyClient(api_key=...)`
  and returns up to 5 snippets per call (title, url, first 240
  chars of content).

To enable in production:

```bash
# .env (NOT committed — local override only)
TAVILY_API_KEY=tvly-...
```

Recommended: scope the key to the Lumen production environment and
rotate quarterly.

## Code-runner sandbox limits

The `code_runner` sub-agent uses RestrictedPython (Zope's
AST-rewriting sandbox) to execute Python. **This is a "safe stub" —
appropriate for tutoring use cases, NOT for arbitrary learner code.**
Phase J will replace it with a Pyodide-in-WASM runner.

Current sandbox:

* **Allowed imports:** `math`, `statistics` (stdlib only, no I/O).
* **Banned:** `__import__` of anything else, `open`, `exec`, `eval`,
  `compile`, `input`, `getattr` on dunders, network, filesystem,
  subprocess, sockets.
* **Hard timeout:** 5 seconds (default). Enforced via
  `asyncio.wait_for` around a `to_thread`-wrapped synchronous
  execution; on POSIX the inner `signal.SIGALRM` adds a second
  layer. On Windows the timeout is detected but not forcibly
  killed — the cooperative wait still terminates the orchestrator
  step.
* **Output cap:** 4000 chars of stdout, ellipsis on overflow.

Failure modes (each returns a `CodeRunResult` without raising):

* Compile error → `exit_code=2`, `error_msg="compile error: ..."`.
* Runtime error → `exit_code=1`, `error_msg="runtime error: ..."`.
* Timeout → `exit_code=1`, `error_msg="execution exceeded 5s deadline"`.
* RestrictedPython missing → `exit_code=2`, `error_msg="...not yet
  available in this environment..."`.

The synthesiser embeds successful stdout in a fenced ```python```
block in the final answer.

## API surface

The chat endpoint `POST /api/v1/tutor/conversations/{id}/messages`
now returns two additional fields:

```json
{
  "user_message": { "...": "..." },
  "assistant_message": { "...": "..." },
  "refused": false,
  "confidence": 4,
  "agent_trace": [
    {
      "tool_name": "retriever",
      "args": {"query": "..."},
      "rationale": "...",
      "result_summary": "found 2 chunk(s) across 2 lesson(s)",
      "result_details": {"chunks": [...], "citations": [...]}
    }
  ]
}
```

Both fields are additive — existing clients that ignore them keep
working unchanged. The chat API is the only edge that surfaces
`agent_trace`; the MCP `ask_tutor` tool returns the legacy
single-shot shape (answer + citations + refused), still backed by
the orchestrator internally.

## Internal call paths

* **Chat API** (`apps/backend/app/api/v1/tutor.py`) →
  `tutor_service.ask_with_trace` → `tutor_orchestrator.orchestrate`.
  The API surfaces the orchestrator's `tool_calls_made` +
  `confidence` to the client.
* **MCP `ask_tutor`** (`apps/backend/app/mcp/tools.py`) →
  `tutor_service.ask` → orchestrator. Returns the legacy shape; MCP
  clients see the multi-agent behaviour transparently.
* **Eval runner** (`apps/backend/app/evals/runner.py`) →
  `tutor_service.ask`. The orchestrator's cost rolls up under
  `feature="eval.tutor"` (the runner overrides the feature slug
  before delegation).

## Frontend surface

The agent-reasoning panel (`components/tutor/agent-reasoning-panel.tsx`)
renders under each assistant tutor turn that produced a tool-call
log. Behaviour:

* **Confidence badge** ("Confidence: N/5") with lime accent at high
  confidence (>= 4).
* **Tabular plan** (Tool | Why | Result). One row per tool call.
* **Per-row expansion** reveals the structured details for that
  tool: chunks for the retriever, snippets for the web searcher,
  stdout for the code runner, etc.
* **Auto-expand** the first assistant turn after the tutor panel
  mounts so a recruiter watching sees the agent thinking
  immediately. Later turns stay collapsed.

The whole panel is opt-in via the disclosure toggle ("Show me how
you got this" / "Hide reasoning") so learners who don't care about
the internals get a clean chat surface.

## Tracing + observability

Every orchestrator turn writes the following `agent_traces` rows
(``feature="tutor.multi_agent"``):

* `plan` — the planner's structured output.
* `tool_call` (one per dispatched tool).
* `sub_agent.<name>` (one per sub-agent, written by the sub-agent
  itself).
* `replan` (when the re-planner runs).
* `synthesis` — the final synthesiser call.

The trace tree is rooted at the `plan` step and rendered by
`/admin/observability` (Phase H7). Drill-down: an admin clicks an
LLM call → sees the linked trace rows; clicks a trace row → sees
the payload (chunks, snippets, args, etc.).

## Future work (Phase J)

* Real Pyodide-in-WASM code execution (replaces RestrictedPython).
* Streaming synthesis (one ChunkResponse per token, rather than a
  single round-trip).
* Tool-budget per user (the cost meter caps spend per user/day; a
  separate tool-call-rounds-per-user cap is a Phase J follow-up).
* `web_searcher` cost metering (today's wrapper records the Tavily
  call as zero-cost in `llm_calls`; a `web_search_cost_logged`
  helper would land Tavily spend in a `web_calls` table).
