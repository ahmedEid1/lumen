"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";

/**
 * Retrieval quality tab — list of recent RAG retrievals + chunks.
 *
 * Each row is one ``retrieval_audits`` record: the query, the
 * course (if any), and the top-K chunks with their cosine-distance
 * scores. Lower score = more similar (pgvector's ``<=>`` operator);
 * the dashboard highlights rows with a high top_score as "low
 * confidence retrieval" — those are the calls most likely to
 * hallucinate.
 */

type RetrievalChunk = {
  chunk_id: string;
  lesson_id: string;
  score: number;
  snippet: string;
};

type RetrievalAuditRow = {
  audit_id: string;
  user_id: string;
  feature: string;
  query: string;
  course_id: string | null;
  chunks: RetrievalChunk[];
  top_score: number | null;
  created_at: string;
};

// Threshold for "low confidence" tinting. Pgvector cosine distance
// is in [0, 2]; <= 0.4 is the comfortable range for our typical
// 384-dim local embeddings on in-distribution queries, > 0.7
// usually means the query didn't really land. Tuned by eye against
// the eval suite; revisit when the suite grows.
const LOW_CONFIDENCE_THRESHOLD = 0.7;

export function RetrievalTab() {
  const q = useQuery({
    queryKey: ["admin", "observability", "retrieval"],
    queryFn: () =>
      api<RetrievalAuditRow[]>(
        "/api/v1/admin/observability/retrieval?limit=50",
      ),
  });

  if (q.isLoading) {
    return (
      <p className="font-mono text-xs text-muted-foreground">
        Loading retrieval audits...
      </p>
    );
  }
  if (q.isError || !q.data) {
    return (
      <p className="font-mono text-xs text-muted-foreground">
        Could not load retrieval audits.
      </p>
    );
  }
  const rows = q.data;
  if (rows.length === 0) {
    return (
      <p className="font-mono text-xs text-muted-foreground">
        No retrieval audits recorded yet. The hook activates when
        the multi-agent tutor (I2) lands and starts calling
        <span className="ms-1 text-foreground">find_relevant_chunks(audit=True)</span>.
      </p>
    );
  }

  return (
    <ul className="flex flex-col gap-3">
      {rows.map((row) => (
        <li key={row.audit_id} className="surface p-4">
          <div className="mb-3 flex flex-wrap items-baseline justify-between gap-3">
            <div className="flex flex-col gap-1">
              <p className="font-display text-base leading-tight tracking-tight text-foreground">
                {row.query}
              </p>
              <p className="font-mono text-xs text-muted-foreground">
                {new Date(row.created_at).toLocaleString()}
                {" · "}
                feature: <span className="text-foreground">{row.feature}</span>
                {row.course_id && (
                  <>
                    {" · "}
                    course: <span className="text-foreground">{row.course_id}</span>
                  </>
                )}
              </p>
            </div>
            <ScoreTag score={row.top_score} />
          </div>
          <ChunkList chunks={row.chunks} />
        </li>
      ))}
    </ul>
  );
}

function ScoreTag({ score }: { score: number | null }) {
  if (score === null) {
    return (
      <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs text-muted-foreground">
        no hits
      </span>
    );
  }
  const tint =
    score > LOW_CONFIDENCE_THRESHOLD
      ? "bg-destructive/15 text-destructive"
      : "bg-muted text-foreground";
  return (
    <span
      className={`rounded px-1.5 py-0.5 font-mono text-xs tabular-nums ${tint}`}
    >
      top: {score.toFixed(3)}
    </span>
  );
}

function ChunkList({ chunks }: { chunks: RetrievalChunk[] }) {
  if (chunks.length === 0) {
    return (
      <p className="font-mono text-xs text-muted-foreground">
        No chunks retrieved.
      </p>
    );
  }
  return (
    <ol className="flex flex-col gap-2">
      {chunks.map((c, i) => (
        <li
          key={c.chunk_id}
          className="flex items-baseline gap-3 border-l-2 border-border pl-3"
        >
          <span className="font-mono text-xs tabular-nums text-muted-foreground">
            #{i + 1}
          </span>
          <div className="flex-1">
            <p className="font-mono text-xs text-foreground">
              {c.snippet}
              {c.snippet.length >= 120 && (
                <span className="text-muted-foreground">…</span>
              )}
            </p>
            <p className="mt-1 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
              chunk {c.chunk_id.slice(0, 10)} · lesson {c.lesson_id.slice(0, 10)} ·{" "}
              <span className="tabular-nums text-foreground">
                {c.score.toFixed(3)}
              </span>
            </p>
          </div>
        </li>
      ))}
    </ol>
  );
}
