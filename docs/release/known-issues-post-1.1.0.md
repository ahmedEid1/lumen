# Known issues — deferred after 1.1.0-agentic Wave 1+2 + post-review cleanup

This document captures issues surfaced by the dual code review (Codex + Claude) of the Wave 1+2 portfolio-activation work, but **deliberately deferred** rather than fixed in the current PR. The intent is to keep the release-PR diff focused and tested; each item below has a clear path forward but is either low-impact, larger than a single commit, or operator-decision-shaped.

All items below are post-`1.1.0-agentic` follow-ups and would land as discrete PRs against `master` or a future `1.2.0` chapter.

---

## Operator decisions required

### KI-1 — Default embedding provider is `local`, but `sentence-transformers` is not in deps — ⚠️ MOOTED 2026-05-25

> The live demo no longer hits this codepath: a Cloudflare Workers AI key
> (`EMBEDDING_PROVIDER=openai` against `https://api.cloudflare.com/.../ai/v1`, model `@cf/baai/bge-small-en-v1.5`) is set in `.env` / `.env.production` and on the AWS box.
> The "wrong default" still exists in source for a fresh `make up` against an unconfigured `.env`, so this is mooted rather than fully resolved. The "Suggested action" below (flip default to `noop` and add the `embeddings-local` extra) still earns its keep for first-run operator-friendliness — keeping the KI open as a polish follow-up.


**Source:** Codex P1 review of pre-existing 1.1.0-agentic code.

**Where:** `apps/backend/app/services/embeddings.py:80` — `EMBEDDING_PROVIDER=local` is the default but the runtime dep `sentence-transformers` is not in `apps/backend/pyproject.toml` or `uv.lock`. On the first default embedding path (e.g. indexing a published course, or the e2e pre-index step) the deferred import raises `ModuleNotFoundError`.

**Why deferred:** Two operator-shaped fixes, neither obviously right:
- (a) Add `sentence-transformers` to deps — pulls in PyTorch + CUDA tooling, **~2 GB** Docker image growth, and ARM64 wheels can be flaky on the small deploy target (t4g.small only has 2 GB RAM total, so even a CPU-only build path is dicey).
- (b) Change the default to `noop` (already wired) — cheap, but means the operator has to opt into embeddings explicitly via `.env`. Probably the right answer for portfolio-demo posture; `noop` returns deterministic zero-vectors which lets the catalog + RAG plumbing work end-to-end without ever hitting an embedding model.

**Suggested action:** Switch default to `noop` in `apps/backend/app/services/embeddings.py`. Document `EMBEDDING_PROVIDER=local` in `.env.example` as the opt-in path with a "requires `pip install sentence-transformers`" note. Defer the full local-model story to a Phase J optional dep extra (`pip install lumen-backend[embeddings-local]`).

**Estimated effort:** 30 min for option (b); a half-day for option (a) including ARM64 wheel testing.

---

### KI-2 — `code_runner` sub-agent has no killable-process sandbox for runaway snippets

**Source:** Codex P2 review of pre-existing I2 code.

**Where:** `apps/backend/app/services/tutor_subagents/code_runner.py:321-323` — `asyncio.wait_for` only cancels the asyncio future, but the snippet runs in a `to_thread` worker; `_execute` ignores the timeout, so a `while True: pass` keeps consuming a thread and CPU after the response is sent. Repeated tutor turns with such snippets can exhaust the thread pool.

**Why deferred:** Real but theoretical risk that needs a proper architectural answer:
- A killable subprocess sandbox (e.g. `firejail` / `bwrap`) on Linux + a Windows-compatible equivalent is real DevOps work.
- The current RestrictedPython AST guards block almost every footgun (`while True` being the main exception); a 5-second compute-time hard cap inside the executor (using `signal.setitimer` on POSIX) is a 30-line stopgap.
- Long-term answer is probably a separate Pyodide-WASM sandbox container running on a strict CPU/mem budget.

**Suggested action:** Land the `setitimer`-based POSIX hard cap as a stopgap before any public deploy traffic. Track the proper sandbox as Phase J work.

**Estimated effort:** 30 min for the stopgap; a week for the proper sandbox.

---

## Dep-graph hygiene

### KI-3 — `traceloop-sdk` (H7 observability) pulls 30+ vendor instrumentations

**Source:** Claude review M3.

**Where:** `apps/backend/uv.lock` (refreshed in commit `b0c3128`) now includes `opentelemetry-instrumentation-{agno,alephalpha,bedrock,chromadb,cohere,crewai,google-generativeai,groq,haystack,lancedb,langchain,llamaindex,marqo,milvus,mistralai,ollama,openai-agents,pinecone,qdrant,replicate,sagemaker,together,transformers,vertexai,voyageai,watsonx,weaviate,writer,...}`.

**Why deferred:** Upstream design issue with `traceloop-sdk`'s blanket dependency, not ours to fix:
- Docker image grows by **hundreds of MB**; cold-start on the t4g.small ARM target grows with it (and matters more on 2 GB RAM than it did on the originally-targeted 24 GB Oracle A1).
- Each instrumentation monkey-patches its target SDK at import time; rare but real risk of import-order breakage.
- The blanket-install pattern is upstream's choice — they may add a `traceloop-sdk[minimal]` extra in a future release.

**Suggested action:** Two mitigation options for a future PR:
- (a) Pin `traceloop-sdk` to a known minimal version and add `opentelemetry-instrumentation-openai` + `-anthropic` directly to `pyproject.toml`. Use a `[tool.uv]` exclude block to suppress the rest.
- (b) Replace `traceloop-sdk` with a hand-rolled OpenLLMetry exporter that only instruments the vendors Lumen actually uses.

**Estimated effort:** 1–2 hours for option (a); a day for option (b).

---

## MCP server hygiene

### KI-4 — `app/mcp/__main__.py` writes a structlog text line to stdout before FastMCP takes over — ✅ RESOLVED 2026-05-25

**Source:** Agent T discovery while fixing the stdio framing test (commit `b4bca55`).

**Where:** `apps/backend/app/mcp/__main__.py` — `log.info("mcp_server_starting", transport="stdio")` fires before `app.main.configure_logging()` runs; the MCP subprocess inherited structlog's default `PrintLoggerFactory()` and wrote a plain-text line to **stdout**.

**Resolution:** `app.core.logging.configure_logging` gained an `stderr: bool = False` flag that wires both `logging.basicConfig(stream=…)` and `structlog.PrintLoggerFactory(file=…)` to `sys.stderr`. `app/mcp/__main__.py` now calls `configure_logging(stderr=args.transport == "stdio")` before any log emission, so the stdio transport's startup log and every subsequent record route to stderr. The HTTP transport keeps the default stdout sink for container-log aggregation parity with the API service.

---

## Doc / comment drift (cosmetic)

### KI-5 — Seed comment claims a 60-second look-back window; actual service uses 120s — ✅ RESOLVED 2026-05-25

**Source:** Claude review M4.

**Where:** `apps/backend/app/seeds/agentic_demo.py:485-486` used to say `"we keep every linked row inside [anchor - 60s, anchor]"`. The actual constant in `apps/backend/app/services/learner_traces.py:83` is `_TRACE_WINDOW_SECONDS = 120`.

**Resolution:** The inline comment now reads `120s (_TRACE_WINDOW_SECONDS in services/learner_traces), so we keep every linked row inside [anchor - 120s, anchor]` and explicitly cross-references the service-layer constant.

---

### KI-6 — Stale "free-tier deploy" references in backend comments — ✅ RESOLVED 2026-05-25

**Source:** Claude review M5.

**Where:** `apps/backend/pyproject.toml:6`, `apps/backend/app/core/rate_limit_metrics.py:11`, `apps/backend/app/core/prod_guards.py:4,140` — plus the broader sweep found `apps/backend/app/seeds/demo.py:1`, `apps/backend/app/cli.py:219`, `apps/backend/tests/test_prod_guards.py:188`, and `.env.example:150` had the same drift.

**Impact:** Internal documentation drift only — no behaviour, no broken links — but multiple different stories about the production target across history.

**Resolution:** Eight drift sites total — reworded to "public demo deploy" / "single-VM demo deploy" / "demo bundle" with cross-refs to `docs/deployment/aws-vps.md` where helpful. Landed across three commits:
- `996a6ed` (3 sites, alongside `legacy/` delete): `pyproject.toml:6`, `rate_limit_metrics.py:11`, `prod_guards.py:4,140`
- `cbe17e4` (4 sites): `seeds/demo.py:1`, `cli.py:219`, `tests/test_prod_guards.py:188`, `.env.example:150`
- `fa5d909` (1 site): `apps/backend/app/seeds/__init__.py:6`

---

### KI-7 — Seed uses fine-grained `feature` slugs the orchestrator never emits — ✅ RESOLVED 2026-05-25

**Source:** Claude review m4 (minor).

**Where:** `apps/backend/app/seeds/agentic_demo.py` — the RetrievalAudit row and three of the four AgentTrace rows previously carried `feature="tutor.multi_agent.{retriever,web_searcher,synth}"`. The real orchestrator at `apps/backend/app/services/tutor_orchestrator.py:91` uses a single `FEATURE = "tutor.multi_agent"` (and the sub-agents inherit `feature=feature` from it for every `record_step` + `RetrievalAudit` call).

**Resolution:** All four rows now use the base `tutor.multi_agent` slug — admin "rows by feature" filtering shows the same single bucket on seeded data that it shows on live data. The two seeded LLM-call rows still use `tutor.multi_agent.plan` / `.synth` because that's also what the orchestrator's `call_logged` invocations emit (`tutor_orchestrator.py` docstring line 32 spells this out).

---

### KI-8 — Bootstrap script writes `/etc/lumen-deploy/deploy.env` but the runbook never reads it — ✅ RESOLVED 2026-05-25

**Source:** Claude review m2 (minor).

**Where:** `scripts/aws-bootstrap.sh` (Block 7) writes `APP_DOMAIN` + `ACME_EMAIL` to `/etc/lumen-deploy/deploy.env`. Runbook step 5 of `docs/deployment/aws-vps.md` used to tell the operator to "mirror these into your .env.production" — manual re-entry.

**Resolution:** The bootstrap exit summary and `aws-vps.md` Step 5 both now instruct the operator to `source /etc/lumen-deploy/deploy.env` before editing `.env.production`, so the file's values populate the shell that fills the production env. The write-then-ignore drift is gone.

---

### KI-9 — Hero screenshot's LLM provider cost-badge reads `noop/lumen-noop-1`

**Source:** Wave-1 A5 known follow-up (already in CHANGELOG).

**Where:** `docs/screenshots/hero.png` — the seeded tutor turn uses the `noop` provider's deterministic output, which stamps `provider="noop"`, `model="lumen-noop-1"` into the `llm_calls` row that renders in the cost badge.

**Suggested action:** Add a `LUMEN_DEMO_PROVIDER_LABEL` env var that lets the seed stamp a chosen provider/model string (e.g. `groq/llama-3.3-70b`) into seeded `llm_calls` rows without calling a remote API. Re-capture the hero with the operator's preferred label after the live demo runs against Groq.

**Estimated effort:** 20 min.

---

### KI-10 — `aws-bootstrap.sh` exit message recommends `python -m app.cli demo-seed` alongside `seed` — ✅ RESOLVED 2026-05-25

**Source:** Claude review m5 (minor).

**Where:** `scripts/aws-bootstrap.sh` exit-summary block + `docs/deployment/aws-vps.md` step 6. (Inherited from the retired `oracle-bootstrap.sh`.)

**Resolution:** Both surfaces now show `python -m app.cli demo-seed` as a commented-out optional extra ("adds 3 browse-only courses on top of the curated multi-agent tutor demo that `seed` already lays down") rather than a default recommendation. Default deploy = curated multi-agent demo; richer catalog = opt-in.

---

## Recommended order if you do a "1.1.0-agentic.1" cleanup pass

1. ~~**KI-1** (embedding default) — affects deploy correctness on first use~~ ⚠️ mooted post-deploy by Cloudflare Workers AI wire-up (`56e49d2`); flipping the default to `noop` still recommended for first-run operator friendliness.
2. ~~**KI-4** (MCP stdout log) — quick spec compliance~~ ✅ done in the post-deploy cleanup commit.
3. ~~**KI-5** (60s/120s comment) — 30-second polish~~ ✅ done in the post-deploy cleanup commit.
4. ~~**KI-7** (seed feature slug) — 5-minute consistency~~ ✅ done in the post-deploy cleanup commit.
5. ~~**KI-6** (free-tier comments) — 15-minute drift cleanup~~ ✅ done in `996a6ed`.
6. ~~**KI-8** + **KI-10** (bootstrap script polish) — 15-minute total~~ ✅ done in the post-deploy cleanup commit.

**What remains:** KI-2 (code_runner sandbox) and KI-3 (traceloop bloat) are Phase-J-scoped. KI-9 (hero screenshot label) is a follow-up tied to a future live-fire re-capture. The rest of the original deferral list is closed.
