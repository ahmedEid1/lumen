"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import type { LessonOut } from "@/lib/api/types";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { api, ApiError } from "@/lib/api/client";
import { type QuizQuestion } from "@/lib/quiz";

export function LessonPlayer({ lesson }: { lesson: LessonOut }) {
  const data = lesson.data as Record<string, any>;
  switch (lesson.type) {
    case "text":
      return (
        <article className="prose prose-neutral dark:prose-invert max-w-none">
          <Markdown body={String(data.body_markdown ?? "")} />
        </article>
      );
    case "video":
      return (
        <div className="aspect-video w-full overflow-hidden rounded-lg border bg-black">
          <video
            controls
            crossOrigin={data.captions_url ? "anonymous" : undefined}
            className="h-full w-full"
            src={String(data.url ?? "")}
          >
            {data.captions_url && (
              // iter 82: instructor-uploaded WebVTT. ``default`` so
              // captions are on out of the gate — accessibility is
              // an opt-out, not an opt-in.
              <track
                kind="captions"
                src={String(data.captions_url)}
                srcLang={String(data.captions_lang ?? "en")}
                label={String(data.captions_label ?? "English")}
                default
              />
            )}
          </video>
        </div>
      );
    case "image":
      return (
        <img
          alt={String(data.alt ?? "")}
          src={String(data.public_url ?? data.asset_key ?? "")}
          className="max-h-[600px] w-full rounded-lg border object-contain"
        />
      );
    case "file":
      return (
        <a
          href={String(data.public_url ?? "#")}
          download={String(data.filename ?? "")}
          className="inline-flex items-center gap-2 rounded-md border px-4 py-2 text-sm hover:bg-muted"
        >
          Download {data.filename ?? "file"}
        </a>
      );
    case "quiz":
      return (
        <Quiz
          lessonId={lesson.id}
          questions={(data.questions ?? []) as QuizQuestion[]}
          pass={Number(data.pass_score ?? 60)}
        />
      );
    default:
      return <p className="text-muted-foreground">Unsupported lesson type: {lesson.type}</p>;
  }
}

function Markdown({ body }: { body: string }) {
  // Tiny inline renderer — paragraphs + headings + bold. For richer content, plug in a library.
  const lines = body.split(/\n+/);
  return (
    <>
      {lines.map((line, i) => {
        if (line.startsWith("# ")) return <h1 key={i}>{line.slice(2)}</h1>;
        if (line.startsWith("## ")) return <h2 key={i}>{line.slice(3)}</h2>;
        if (line.startsWith("### ")) return <h3 key={i}>{line.slice(4)}</h3>;
        return <p key={i} dangerouslySetInnerHTML={{ __html: inline(line) }} />;
      })}
    </>
  );
}

function inline(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
}

type QuizResult = {
  score: number;
  pass_score: number;
  passed: boolean;
  correct_count: number;
  total: number;
  results: { question_id: string; correct: boolean }[];
};

type QuizAttempt = {
  id: string;
  score: number;
  passed: boolean;
  submitted_at: string;
};

function Quiz({
  lessonId,
  questions,
  pass,
}: {
  lessonId: string;
  questions: QuizQuestion[];
  pass: number;
}) {
  const [answers, setAnswers] = useState<Record<string, string[] | string>>({});
  const [result, setResult] = useState<QuizResult | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [history, setHistory] = useState<QuizAttempt[]>([]);
  const submitted = result !== null;
  const correctByQuestion = new Map(result?.results.map((r) => [r.question_id, r.correct]) ?? []);

  // Load past attempts on mount so a returning learner sees "you've
  // tried this 3 times" before they submit again. Refreshed after
  // every submit so the new attempt shows immediately.
  useEffect(() => {
    loadHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lessonId]);
  async function loadHistory() {
    try {
      const rows = await api<QuizAttempt[]>(
        `/api/v1/me/progress/lessons/${lessonId}/quiz/attempts`,
      );
      setHistory(rows);
    } catch {
      // History is a nice-to-have; if the endpoint hiccups, the
      // quiz itself still works.
    }
  }

  function toggle(q: QuizQuestion, choice: string) {
    setAnswers((prev) => {
      if (q.kind === "single") return { ...prev, [q.id]: [choice] };
      const cur = (prev[q.id] as string[]) ?? [];
      return {
        ...prev,
        [q.id]: cur.includes(choice) ? cur.filter((c) => c !== choice) : [...cur, choice],
      };
    });
  }

  async function submit() {
    setSubmitting(true);
    try {
      const out = await api<QuizResult>(`/api/v1/me/progress/lessons/${lessonId}/quiz`, {
        method: "POST",
        body: { answers },
      });
      setResult(out);
      // The new attempt should appear in the history strip below.
      await loadHistory();
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "Could not submit quiz";
      toast.error(msg);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-6">
      {history.length > 0 && (
        <div className="rounded-lg border bg-muted/30 p-3 text-xs">
          <div className="mb-2 font-medium text-muted-foreground">
            Past attempts ({history.length})
          </div>
          <ol className="flex flex-wrap gap-2">
            {history.map((a) => (
              <li
                key={a.id}
                className={[
                  "inline-flex items-center gap-1 rounded border px-2 py-0.5 tabular-nums",
                  a.passed
                    ? "border-emerald-600/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
                    : "border-muted-foreground/30 text-muted-foreground",
                ].join(" ")}
                title={new Date(a.submitted_at).toLocaleString()}
              >
                {a.score}% {a.passed ? "✓" : ""}
              </li>
            ))}
          </ol>
        </div>
      )}
      {questions.map((q, idx) => {
        const given = answers[q.id];
        const questionCorrect = correctByQuestion.get(q.id);
        return (
          <div key={q.id} className="rounded-lg border p-4">
            <div className="mb-3 flex items-start justify-between gap-2">
              <p className="font-medium">
                Q{idx + 1}. {q.prompt}
              </p>
              <div className="flex items-center gap-2">
                {submitted && (
                  <Badge variant={questionCorrect ? "default" : "outline"}>
                    {questionCorrect ? "correct" : "incorrect"}
                  </Badge>
                )}
                <Badge variant="muted">{q.kind}</Badge>
              </div>
            </div>
            {q.kind === "short" ? (
              <input
                type="text"
                value={typeof given === "string" ? given : ""}
                onChange={(e) => setAnswers((p) => ({ ...p, [q.id]: e.target.value }))}
                disabled={submitted}
                className="h-10 w-full rounded-md border bg-background px-3 text-sm disabled:opacity-70"
                placeholder="Your answer"
              />
            ) : (
              <ul className="space-y-2">
                {q.choices?.map((c) => {
                  const selected = (given as string[] | undefined)?.includes(c.id);
                  const isCorrect = submitted && q.answer_keys.includes(c.id);
                  return (
                    <li key={c.id}>
                      <button
                        onClick={() => toggle(q, c.id)}
                        disabled={submitted}
                        className={[
                          "w-full rounded border px-3 py-2 text-start text-sm",
                          selected ? "border-primary bg-primary/5" : "",
                          isCorrect ? "border-emerald-500 bg-emerald-500/10" : "",
                        ].join(" ")}
                      >
                        {c.text}
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        );
      })}
      <div className="flex items-center justify-between">
        {!submitted ? (
          <Button onClick={submit} disabled={submitting}>
            {submitting ? "Submitting…" : "Submit quiz"}
          </Button>
        ) : (
          <p
            className={`text-sm ${result.passed ? "text-emerald-600" : "text-destructive"}`}
            role="status"
          >
            You scored {result.score}% ({result.correct_count} of {result.total}).{" "}
            {result.passed ? "Nice work — lesson marked complete!" : `Pass mark is ${pass}%. Try again.`}
          </p>
        )}
        {submitted && (
          <Button
            variant="outline"
            onClick={() => {
              setAnswers({});
              setResult(null);
            }}
          >
            Retake
          </Button>
        )}
      </div>
    </div>
  );
}
