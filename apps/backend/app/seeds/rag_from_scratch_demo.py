"""Building a RAG system from scratch — demo course content.

The fifth seeded demo course, authored for L20.6 of the post-redesign
roadmap. Self-referential by design: when a recruiter on /demo asks the
Lumen tutor "how does this RAG system work?", the answer cites lessons
from THIS course — which is itself the system being described.

Each lesson stays ≤220 words so the embedding pipeline indexes it
quickly during the post-seed reindex step. Topics are picked to map
1:1 onto the L21 architectural decisions the case-study at L30 will
expand on, so a learner who finishes the course has a head start on
reading the case study.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.models.course import (
    Course,
    CourseStatus,
    Difficulty,
    Lesson,
    LessonType,
    Module,
    Subject,
    Tag,
)
from app.models.user import User


def _text(body_markdown: str) -> dict[str, Any]:
    return {"type": "text", "body_markdown": body_markdown}


def _quiz(question: str, choices: list[tuple[str, str]], answer_id: str) -> dict[str, Any]:
    return {
        "type": "quiz",
        "pass_score": 60,
        "questions": [
            {
                "id": "q1",
                "prompt": question,
                "kind": "single",
                "choices": [{"id": cid, "text": text} for cid, text in choices],
                "answer_keys": [answer_id],
            }
        ],
    }


RAG_FROM_SCRATCH_MODULES: list[dict[str, Any]] = [
    # ---------------------------------------------------------------- #
    # Module 1 — What RAG is (and when not to use it)                 #
    # ---------------------------------------------------------------- #
    {
        "title": "What retrieval-augmented generation is",
        "description": "The problem RAG solves, and when fine-tuning would be a better tool.",
        "lessons": [
            {
                "title": "Why RAG, not fine-tuning",
                "type": LessonType.text,
                "data": _text(
                    "Large language models are trained on a snapshot of the "
                    "internet. Anything that changed after the training "
                    "cutoff, or that lives behind your auth wall, isn't in "
                    "the weights. Two ways to bridge the gap:\n\n"
                    "- **Fine-tuning** updates the weights to encode new "
                    "  facts. Expensive (GPU-hours, rerun for every update), "
                    "  brittle (subtle skill regressions), and forgetful — "
                    "  a fact embedded in weights loses its source.\n"
                    "- **Retrieval-augmented generation** keeps the weights "
                    "  frozen and *retrieves* the right context per query, "
                    "  inserting it into the prompt. Cheap to update (just "
                    "  reindex), citation-friendly (you know which chunk "
                    "  the answer leaned on), and easier to audit.\n\n"
                    "Lumen's tutor is RAG end-to-end. The case for fine-"
                    "tuning kicks in only when you need to teach a model a "
                    "new *skill* (output a specific JSON shape, follow a "
                    "very specific style) — not new *facts*."
                ),
            },
            {
                "title": "The hallucination problem",
                "type": LessonType.text,
                "data": _text(
                    "Without retrieval, a model asked about a fact outside "
                    "its training distribution will *confabulate* — produce "
                    "a plausible-sounding answer with no basis. Common "
                    "examples: invented paper citations, fabricated API "
                    "method names, wrong version numbers.\n\n"
                    "Retrieval defuses this two ways:\n\n"
                    "1. **Grounding.** The model is prompted with concrete "
                    "   passages it can quote and cite. Telling the model "
                    "   'answer only from the context below; if the context "
                    "   doesn't cover the question, say so' shifts the "
                    "   incentive from guess to refuse.\n"
                    "2. **Falsifiability.** Citations let a human (or an "
                    "   eval harness) compare answer to source. If the cited "
                    "   passage doesn't support the claim, the answer is "
                    "   wrong in a debuggable way.\n\n"
                    "Lumen's tutor refuses to answer without at least one "
                    "retrieved chunk. The L25 eval suite scores grounding "
                    "explicitly: answer + cited chunk → judge labels "
                    "supported / partially-supported / unsupported."
                ),
            },
            {
                "title": "Quick check: RAG vs fine-tuning",
                "type": LessonType.quiz,
                "data": _quiz(
                    "When is RAG strictly better than fine-tuning?",
                    [
                        ("a", "When you need to teach the model a new skill / output shape"),
                        ("b", "When the model is brand new and unknown"),
                        (
                            "c",
                            "When you need cite-able, updatable knowledge without retraining",
                        ),
                        ("d", "When latency is the binding constraint"),
                    ],
                    "c",
                ),
            },
        ],
    },
    # ---------------------------------------------------------------- #
    # Module 2 — Embeddings 101                                       #
    # ---------------------------------------------------------------- #
    {
        "title": "Embeddings 101",
        "description": "What an embedding is, why cosine similarity, and how pgvector stores them.",
        "lessons": [
            {
                "title": "What an embedding is",
                "type": LessonType.text,
                "data": _text(
                    "An embedding is a fixed-length vector of floats that "
                    "represents the *meaning* of a piece of text. Two texts "
                    "with similar meanings have vectors close together in "
                    "high-dimensional space; two texts with different "
                    "meanings sit far apart.\n\n"
                    "Concretely: Lumen's embedding model "
                    "(`@cf/baai/bge-small-en-v1.5` on Cloudflare Workers AI) "
                    "outputs a 384-dimensional vector per text. 'how do I "
                    "fix the variance error' lands near 'why is string not "
                    "assignable to T' in that space even though there's no "
                    "exact word overlap.\n\n"
                    "The vectors come from running text through a model "
                    "trained on contrastive pairs — 'this sentence means "
                    "the same as that sentence, but not that other one.' "
                    "What the model learned shows up as geometric structure: "
                    "synonyms cluster, opposites separate, related concepts "
                    "form neighbourhoods. That structure is what makes "
                    "retrieval work."
                ),
            },
            {
                "title": "Cosine similarity and pgvector storage",
                "type": LessonType.text,
                "data": _text(
                    "To 'find similar text' we compare embeddings via "
                    "**cosine similarity** — `1 - cos(angle between "
                    "vectors)`. Cosine ignores vector *magnitude* and only "
                    "looks at *direction*, which matches the intuition "
                    "'these two texts mean the same thing, ignoring length.'\n\n"
                    "Lumen stores embeddings in Postgres with the **pgvector** "
                    "extension:\n\n"
                    "```sql\n"
                    "CREATE TABLE lesson_chunks (\n"
                    "  id text PRIMARY KEY,\n"
                    "  lesson_id text NOT NULL,\n"
                    "  content text NOT NULL,\n"
                    "  embedding vector(384)\n"
                    ");\n"
                    "CREATE INDEX ON lesson_chunks USING ivfflat\n"
                    "  (embedding vector_cosine_ops) WITH (lists = 100);\n"
                    "```\n\n"
                    "The `ivfflat` index makes nearest-neighbour search "
                    "sub-linear; without it, a query scans every row. The "
                    "`<=>` operator returns cosine distance, and `ORDER BY "
                    "embedding <=> :query_vector LIMIT 5` is the entire "
                    "retrieval primitive."
                ),
            },
        ],
    },
    # ---------------------------------------------------------------- #
    # Module 3 — Chunking + retrieval                                 #
    # ---------------------------------------------------------------- #
    {
        "title": "Chunking and hybrid retrieval",
        "description": "Splitting documents, hybrid (vector + BM25) search, and reranking.",
        "lessons": [
            {
                "title": "Why chunking matters",
                "type": LessonType.text,
                "data": _text(
                    "Embedding models have a context window (~512 tokens "
                    "for `bge-small`). Pass a 10-page document in and the "
                    "model either truncates or smears 10 pages of meaning "
                    "into one vector — *neither* gives good retrieval.\n\n"
                    "Lumen chunks every lesson into ~120-200-word slices. "
                    "Chunks are small enough that each one is *about* a "
                    "single concept, so its embedding is a sharp pointer "
                    "into the semantic space. They overlap slightly (50 "
                    "tokens) so a concept that straddles two chunks isn't "
                    "lost to the boundary.\n\n"
                    "Bad chunking is the single most common reason a RAG "
                    "system 'retrieves rubbish'. Symptoms: relevant content "
                    "exists but doesn't surface; cited passage is too long "
                    "to be useful; cited passage is too short and lacks "
                    "context. The fix is rarely a better embedding model "
                    "— it's a better chunker."
                ),
            },
            {
                "title": "Hybrid search: vector + BM25",
                "type": LessonType.text,
                "data": _text(
                    "Vector search is great at semantic similarity but bad "
                    "at *exact* matches. Ask 'what does `selectinload` do' "
                    "and pure-vector might miss because the embedding model "
                    "wasn't trained to weight the literal token.\n\n"
                    "**BM25** is the classic keyword scoring algorithm — "
                    "term frequency × inverse document frequency, with "
                    "length normalisation. Fast on Postgres via `tsvector` "
                    "+ `ts_rank`. Catches exact matches by construction.\n\n"
                    "Hybrid search runs both, then combines the rankings — "
                    "either by score fusion (`alpha * vector_score + "
                    "(1-alpha) * bm25_score`) or **reciprocal rank fusion** "
                    "(`sum(1 / (k + rank_in_each_list))`). RRF is the "
                    "current default in Lumen's retriever because it "
                    "needs no per-corpus tuning of the alpha weight.\n\n"
                    "Result: when you ask the tutor about a specific API "
                    "name, BM25 surfaces the exact lesson; when you ask "
                    "about a concept, vector search surfaces the one that "
                    "shares meaning even if it uses different words."
                ),
            },
        ],
    },
    # ---------------------------------------------------------------- #
    # Module 4 — Building + evaluating the loop                       #
    # ---------------------------------------------------------------- #
    {
        "title": "Building and evaluating the loop",
        "description": "Index → retrieve → ground → generate, then prove it works.",
        "lessons": [
            {
                "title": "The end-to-end loop",
                "type": LessonType.text,
                "data": _text(
                    "A turn of Lumen's tutor:\n\n"
                    "1. **Embed the question.** One API call to the "
                    "   embedding model; the question becomes a 384-dim "
                    "   vector.\n"
                    "2. **Retrieve top-K.** `SELECT … ORDER BY embedding "
                    "   <=> :q LIMIT 8` against `lesson_chunks`; pgvector "
                    "   uses the `ivfflat` index for sub-linear search.\n"
                    "3. **(L21+) Rerank.** A small cross-encoder rescores "
                    "   the 8 candidates and picks the top 4. Cheap (~20ms) "
                    "   but tightens grounding.\n"
                    "4. **Compose the prompt.** System instruction + the 4 "
                    "   retrieved chunks (formatted with their lesson IDs "
                    "   so the model can cite them) + the user's question.\n"
                    "5. **Generate.** One call to the LLM (Groq Llama 3.3 "
                    "   for the demo). The model produces the answer, "
                    "   citing chunk IDs inline.\n"
                    "6. **Post-process.** Validate that every cited ID "
                    "   exists in the retrieved set; refuse if the model "
                    "   hallucinated a citation.\n\n"
                    "That's the whole loop. Everything else (sub-agents, "
                    "code-runner, web search) is a richer step 5."
                ),
            },
            {
                "title": "Evaluating a RAG system",
                "type": LessonType.text,
                "data": _text(
                    "Three signals you measure independently:\n\n"
                    "- **Retrieval recall.** Of the K chunks retrieved, "
                    "  how many contain the answer? Computed against a "
                    "  gold set where every question has the 'right' chunk "
                    "  ID. Lumen's eval suite (L25) reports recall@8.\n"
                    "- **Grounding / faithfulness.** Is the answer "
                    "  supported by the retrieved chunks? Computed by an "
                    "  LLM-as-judge: 'does the answer claim X; does any "
                    "  cited chunk say X?' Lumen scores this 0-5 per turn.\n"
                    "- **Answer quality.** Holistic — would a human "
                    "  marker pass this answer? Also LLM-as-judge, with a "
                    "  rubric.\n\n"
                    "These split the failure modes apart. Low recall means "
                    "fix the retriever (chunking, hybrid, reranker). Low "
                    "faithfulness with high recall means fix the prompt "
                    "(stricter grounding instruction). Low answer quality "
                    "with both above okay means the underlying model isn't "
                    "strong enough — time to consider a bigger model.\n\n"
                    "Lumen's public `/eval` surface (L27/L28) shows these "
                    "three signals on every published run so you can audit "
                    "what shipped."
                ),
            },
        ],
    },
]


async def apply(
    db,
    *,
    instructor: User,
    programming: Subject,
    tags: dict[str, Tag],
) -> Course:
    """Upsert the RAG-from-scratch course. Idempotent on re-run.

    Uses the same _build_course shape as the rest of the demo bundle.
    """
    slug = "rag-from-scratch"
    existing = await db.execute(select(Course).where(Course.slug == slug))
    course = existing.scalar_one_or_none()
    if course is not None:
        return course

    course = Course(
        owner_id=instructor.id,
        subject_id=programming.id,
        title="Building a RAG system from scratch",
        slug=slug,
        overview=(
            "The exact architecture Lumen's tutor runs on, taught from "
            "first principles. Embeddings, chunking, hybrid retrieval, "
            "evaluation — the lessons here are what the tutor cites back "
            "when a learner asks 'how does this work?'"
        ),
        learning_outcomes=[
            "Explain when RAG is the right tool vs fine-tuning",
            "Reason about embeddings + cosine similarity in pgvector",
            "Choose chunk sizes and combine vector + BM25 retrieval",
            "Evaluate a RAG system on recall, grounding, and answer quality",
        ],
        difficulty=Difficulty.intermediate,
        status=CourseStatus.published,
        published_at=datetime.now(UTC),
        is_featured=True,
    )
    course.tags = [
        tags.get("demo", tags.get("python")),  # demo tag should exist; python as backstop
    ]
    db.add(course)
    await db.flush()

    for m_idx, mod_spec in enumerate(RAG_FROM_SCRATCH_MODULES):
        module = Module(
            course_id=course.id,
            title=mod_spec["title"],
            description=mod_spec.get("description", ""),
            order=m_idx,
        )
        db.add(module)
        await db.flush()
        for l_idx, lesson_spec in enumerate(mod_spec["lessons"]):
            db.add(
                Lesson(
                    module_id=module.id,
                    title=lesson_spec["title"],
                    type=lesson_spec["type"],
                    order=l_idx,
                    data=lesson_spec["data"],
                )
            )
        await db.flush()

    return course
