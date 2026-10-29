"""Building a RAG system from scratch — demo course content.

The fifth seeded demo course, authored for L20.6 of the post-redesign
roadmap. Self-referential by design: when a recruiter on /demo asks the
Lumen tutor "how does this RAG system work?", the answer cites lessons
from THIS course — which is itself the system being described.

Each lesson stays ≤220 words so it fits in one embedding chunk. Every
claim about Lumen itself must match the code (HNSW cosine top-k with the
ACL in SQL, ~500-token chunks, citation filter, LLM-judge evals); where
the textbook technique (BM25, hybrid, reranking, recall@k) isn't built,
the lesson says so. ``apply`` is insert-only, so after editing this text
on a live install, update the existing lessons and reindex the course.
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
    ModerationState,
    Module,
    Subject,
    Tag,
    Visibility,
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


RAG_FROM_SCRATCH_OVERVIEW = (
    "How retrieval-augmented generation works, from first principles: "
    "embeddings, chunking, retrieval, grounding and evaluation. Each lesson "
    "is checked against the code of Lumen's own tutor, and says so where "
    "Lumen takes a simpler path than the textbook. These lessons are what "
    "the tutor cites when a learner asks how it works."
)

RAG_FROM_SCRATCH_OUTCOMES = [
    "Explain when RAG is the right tool vs fine-tuning",
    "Reason about embeddings and cosine distance in pgvector",
    "Choose chunk sizes and know when keyword or hybrid search helps",
    "Evaluate a RAG system on recall, faithfulness and helpfulness",
]


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
                    "  behaviour. Expensive (GPU-hours, rerun for every "
                    "  update), brittle (subtle skill regressions), and it "
                    "  loses the source: you can't point at where a fact came "
                    "  from.\n"
                    "- **Retrieval-augmented generation** keeps the weights "
                    "  frozen and *retrieves* the right context per query, "
                    "  inserting it into the prompt. Cheap to update (just "
                    "  reindex), citation-friendly (you know which passage "
                    "  the answer leaned on), and easier to audit.\n\n"
                    "Lumen's tutor is RAG end to end: every answer is "
                    "generated from passages of the course you are in. "
                    "Fine-tuning earns its cost when you need to teach a "
                    "model a new *skill* (a specific output shape, a house "
                    "style), not new *facts*."
                ),
            },
            {
                "title": "The hallucination problem",
                "type": LessonType.text,
                "data": _text(
                    "Without retrieval, a model asked about a fact outside "
                    "its training data will *confabulate*: produce a "
                    "plausible-sounding answer with no basis. Common "
                    "examples are invented paper citations, made-up API "
                    "method names and wrong version numbers.\n\n"
                    "Retrieval helps in two ways:\n\n"
                    "1. **Grounding.** The model gets concrete passages it "
                    "   can quote and cite. An instruction like 'answer only "
                    "   from the context below; if it doesn't cover the "
                    "   question, say so' shifts the incentive from guessing "
                    "   to declining.\n"
                    "2. **Falsifiability.** Citations let a person, or an "
                    "   eval harness, compare the answer with its source. If "
                    "   the cited passage doesn't support the claim, the "
                    "   answer is wrong in a way you can debug.\n\n"
                    "Lumen's tutor prompt carries exactly that instruction, "
                    "and asks the model to cite each claim as `[L:<lesson "
                    "id>]`. Before the answer is shown, any citation that "
                    "points at a lesson outside the retrieved set is dropped, "
                    "so a learner never gets a link to a source the model "
                    "didn't see."
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
        "description": "What an embedding is, why cosine distance, and how pgvector stores them.",
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
                    "assignable to T' in that space even though the two "
                    "share almost no words.\n\n"
                    "The vectors come from a model trained on contrastive "
                    "pairs: 'this sentence means the same as that one, but "
                    "not that other one.' What it learned shows up as "
                    "geometry. Synonyms cluster, unrelated topics separate, "
                    "and related concepts form neighbourhoods. That "
                    "structure is what makes retrieval work."
                ),
            },
            {
                "title": "Cosine distance and pgvector storage",
                "type": LessonType.text,
                "data": _text(
                    "To find similar text we compare embeddings by **cosine "
                    "distance**, `1 - cos(angle between the vectors)`. Cosine "
                    "ignores a vector's *length* and looks only at its "
                    "*direction*, which matches the intuition 'these two "
                    "texts mean the same thing'.\n\n"
                    "Lumen stores embeddings in Postgres with the "
                    "**pgvector** extension, one row per lesson chunk:\n\n"
                    "```sql\n"
                    "CREATE TABLE lesson_chunks (\n"
                    "  id text PRIMARY KEY,\n"
                    "  lesson_id text NOT NULL,\n"
                    "  chunk_index int NOT NULL,\n"
                    "  text text NOT NULL,\n"
                    "  embedding vector(384)\n"
                    ");\n"
                    "CREATE INDEX ON lesson_chunks\n"
                    "  USING hnsw (embedding vector_cosine_ops);\n"
                    "```\n\n"
                    "The **HNSW** index is a layered proximity graph: search "
                    "starts at a coarse layer and walks towards the nearest "
                    "neighbours, so it doesn't scan every row. The `<=>` "
                    "operator returns cosine distance, and `ORDER BY "
                    "embedding <=> :query_vector LIMIT 6` is the core of the "
                    "retrieval step."
                ),
            },
        ],
    },
    # ---------------------------------------------------------------- #
    # Module 3 — Chunking + retrieval                                 #
    # ---------------------------------------------------------------- #
    {
        "title": "Chunking and retrieval choices",
        "description": "Splitting lessons into chunks, and when keyword or hybrid search helps.",
        "lessons": [
            {
                "title": "Why chunking matters",
                "type": LessonType.text,
                "data": _text(
                    "Embedding models have a context window (about 512 "
                    "tokens for `bge-small`). Pass a 10-page document in and "
                    "the model either truncates it or smears 10 pages of "
                    "meaning into one vector. Neither retrieves well.\n\n"
                    "Lumen splits each lesson into windows of about 500 "
                    "tokens (roughly 375 words, estimated from the word "
                    "count rather than a real tokenizer), with a 50-token "
                    "overlap so a concept that straddles a boundary still "
                    "lands whole in one chunk. Most lessons fit in a single "
                    "chunk; long ones become several.\n\n"
                    "Bad chunking is the most common reason a RAG system "
                    "'retrieves rubbish'. The symptoms: relevant content "
                    "exists but doesn't surface, the cited passage is too "
                    "long to be useful, or it is too short to carry its "
                    "context. The fix is rarely a better embedding model. "
                    "It's usually a better chunker, for example one that "
                    "splits on headings instead of word counts."
                ),
            },
            {
                "title": "Vector, keyword and hybrid search",
                "type": LessonType.text,
                "data": _text(
                    "Vector search is good at meaning and weaker at *exact* "
                    "matches. Ask 'what does `selectinload` do' and a pure "
                    "vector search can rank a loosely related lesson above "
                    "the one that names the function.\n\n"
                    "**BM25** is the classic keyword score: term frequency "
                    "times inverse document frequency, with length "
                    "normalisation. Postgres full-text search (`tsvector` "
                    "plus `ts_rank`) gives you a close relative of it, and "
                    "it catches exact terms by construction.\n\n"
                    "**Hybrid search** runs both and merges the rankings, "
                    "either with a weighted score or with **reciprocal rank "
                    "fusion**: `sum(1 / (k + rank))` across the lists, which "
                    "needs no per-corpus weight tuning.\n\n"
                    "Lumen's tutor uses vector search only. Postgres "
                    "full-text search powers the course catalog's search "
                    "box, not the tutor. That is a deliberate starting "
                    "point: course-scoped corpora are small, and hybrid "
                    "retrieval is worth its extra moving parts once evals "
                    "show exact-term questions being missed."
                ),
            },
        ],
    },
    # ---------------------------------------------------------------- #
    # Module 4 — Building + evaluating the loop                       #
    # ---------------------------------------------------------------- #
    {
        "title": "Building and evaluating the loop",
        "description": "Index, retrieve, ground, generate, then measure it.",
        "lessons": [
            {
                "title": "The end-to-end loop",
                "type": LessonType.text,
                "data": _text(
                    "One turn of Lumen's web tutor:\n\n"
                    "1. **Embed the question.** One call to the embedding "
                    "   model turns it into a 384-dimensional vector.\n"
                    "2. **Retrieve the top chunks.** A single SQL query "
                    "   orders `lesson_chunks` by `embedding <=> :q` and "
                    "   takes the top 6. The same query restricts results to "
                    "   the current course, skips deleted lessons and applies "
                    "   the access check, so the tutor can't retrieve text the "
                    "   learner isn't allowed to read.\n"
                    "3. **Compose the prompt.** The system instruction, then "
                    "   each chunk under a `Lesson L<id>: <title>` header so "
                    "   the model can cite it, then the question.\n"
                    "4. **Generate.** One streamed call to the LLM "
                    "   (`gpt-oss-120b` on Groq, with a smaller model as "
                    "   fallback). The answer cites lessons inline.\n"
                    "5. **Post-process.** Citations to lessons outside the "
                    "   retrieved set are dropped; the rest become links.\n"
                    "6. **Audit.** The query, the chunks returned and their "
                    "   distances are logged, so a bad answer can be traced "
                    "   to the retrieval that produced it.\n\n"
                    "That's the whole loop. Rerankers, hybrid search and "
                    "extra tools are refinements of steps 2 and 4."
                ),
            },
            {
                "title": "Evaluating a RAG system",
                "type": LessonType.text,
                "data": _text(
                    "Measure three things separately:\n\n"
                    "- **Retrieval recall.** Of the chunks retrieved, does "
                    "  any contain the answer? You need a gold set where "
                    "  every question names the passage that answers it, "
                    "  then report recall@k.\n"
                    "- **Faithfulness and citations.** Is every claim "
                    "  supported by the course, and does each cited lesson "
                    "  say what it is cited for? This usually needs an LLM "
                    "  judge with a fixed rubric.\n"
                    "- **Helpfulness.** Is the answer the right shape and "
                    "  length for the question?\n\n"
                    "Splitting them tells you what to fix. Low recall: fix "
                    "the retriever (chunking, hybrid search, a reranker). "
                    "Good recall but low faithfulness: tighten the prompt. "
                    "Both fine but weak answers: try a stronger model.\n\n"
                    "Lumen's tutor eval runs a golden question set through "
                    "the tutor, and an LLM judge scores each answer 0-5 for "
                    "faithfulness, citation correctness and helpfulness "
                    "against a reference answer and the lessons it must "
                    "cite. A retrieval recall metric is the next one to add."
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
        overview=RAG_FROM_SCRATCH_OVERVIEW,
        learning_outcomes=RAG_FROM_SCRATCH_OUTCOMES,
        difficulty=Difficulty.intermediate,
        status=CourseStatus.published,  # noqa: published-check — seed write
        # Seed the FULL publicly-listed state (R-C1′ /
        # app.services.visibility.is_publicly_listed) — mirrors
        # moderation.approve_course (visibility public + moderation_state
        # approved). Without it a fresh stack (no S2 backfill migration)
        # existence-hides this published course (404).
        visibility=Visibility.public,
        moderation_state=ModerationState.approved,
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
