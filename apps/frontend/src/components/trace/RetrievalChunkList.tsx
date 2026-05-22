"use client";

/**
 * Renders the retriever's chunks with similarity scores in
 * mono + tabular-nums.
 *
 * Lumen v2 Phase I4. The chunk list is the "actually grounded in
 * course material" proof — it's the literal RAG receipt. Each
 * chunk row shows:
 *
 *   - lesson_id in mono with the lime accent
 *   - score, tabular-nums for clean column alignment
 *   - the chunk snippet body
 *
 * Used both inline inside :class:`TraceStepCard` when the step's
 * payload carries retriever chunks AND as a top-level audit
 * renderer when the trace surface lists ``retrieval_audits``
 * separately.
 */

import { cn } from "@/lib/utils";

export interface ChunkLike {
  /** Either ``lesson_id`` or ``chunk_id`` is enough to identify the row. */
  lesson_id?: string;
  chunk_id?: string;
  lesson_title?: string;
  /** Distance / similarity score. Lower is usually better for cosine distance. */
  score?: number;
  /** Either ``text`` (from the orchestrator) or ``snippet`` (from retrieval_audits). */
  text?: string;
  snippet?: string;
}

export interface RetrievalChunkListProps {
  chunks: ChunkLike[];
  /** Override the empty-state copy. Defaults to "No chunks retrieved." */
  emptyLabel?: string;
  className?: string;
}

function formatScore(value: number | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return value.toFixed(3);
}

export function RetrievalChunkList({
  chunks,
  emptyLabel = "No chunks retrieved.",
  className,
}: RetrievalChunkListProps) {
  if (chunks.length === 0) {
    return (
      <p
        className={cn(
          "font-mono text-xs text-muted-foreground",
          className,
        )}
        data-testid="retrieval-chunk-list-empty"
      >
        {emptyLabel}
      </p>
    );
  }
  return (
    <ul
      className={cn("flex flex-col gap-2", className)}
      data-testid="retrieval-chunk-list"
    >
      {chunks.map((chunk, idx) => {
        const id = chunk.lesson_id ?? chunk.chunk_id ?? `chunk-${idx}`;
        const body = chunk.text ?? chunk.snippet ?? "";
        return (
          <li
            key={`${id}-${idx}`}
            data-testid="retrieval-chunk-row"
            className="rounded-md border border-border/60 bg-card/40 p-3"
          >
            <div className="flex flex-wrap items-baseline gap-2 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
              <span className="text-primary normal-case tracking-normal">
                L:{chunk.lesson_id ?? chunk.chunk_id ?? "?"}
              </span>
              {chunk.lesson_title ? (
                <span className="normal-case tracking-normal text-foreground/70">
                  {chunk.lesson_title}
                </span>
              ) : null}
              <span aria-hidden>·</span>
              <span className="tabular-nums normal-case tracking-normal">
                score {formatScore(chunk.score)}
              </span>
            </div>
            {body ? (
              <p className="mt-1 whitespace-pre-wrap font-body text-xs text-foreground/80">
                {body}
              </p>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}
