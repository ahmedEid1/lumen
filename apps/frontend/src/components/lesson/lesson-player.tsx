"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import type { LessonOut } from "@/lib/api/types";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Glyph } from "@/components/lumen/glyph";
import { api, ApiError } from "@/lib/api/client";
import { type QuizQuestion } from "@/lib/quiz";
import { useT } from "@/lib/i18n/provider";
import type { MessageKey } from "@/lib/i18n/messages/en";

export function LessonPlayer({ lesson }: { lesson: LessonOut }) {
  const t = useT();
  const data = lesson.data as Record<string, any>;
  switch (lesson.type) {
    case "text":
      return (
        <article className="prose prose-neutral max-w-none font-body dark:prose-invert prose-headings:font-display prose-headings:text-gold/90">
          <Markdown body={String(data.body_markdown ?? "")} />
        </article>
      );
    case "video":
      return (
        <div className="aspect-video w-full overflow-hidden rounded-md border border-gold/25 bg-black">
          <video
            controls
            crossOrigin={data.captions_url ? "anonymous" : undefined}
            className="h-full w-full"
            src={String(data.url ?? "")}
          >
            {data.captions_url && (
              // Instructor-uploaded WebVTT. `default` so
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
        // eslint-disable-next-line @next/next/no-img-element
        <img
          alt={String(data.alt ?? "")}
          src={String(data.public_url ?? data.asset_key ?? "")}
          className="max-h-[600px] w-full rounded-md border border-gold/20 object-contain"
        />
      );
    case "file":
      return (
        <a
          href={String(data.public_url ?? "#")}
          download={String(data.filename ?? "")}
          className="inline-flex items-center gap-2 rounded-md border border-gold/40 bg-gold/5 px-4 py-2 font-body text-sm text-gold transition-colors hover:bg-gold/10"
        >
          <Glyph name="scroll" size={16} mode="tint" />
          {t("player.download", { name: String(data.filename ?? "") })}
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
      return (
        <p className="font-body italic text-muted-foreground">
          {t("player.unsupported", { type: lesson.type })}
        </p>
      );
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
  const t = useT();
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
      await loadHistory();
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : t("quiz.submitError");
      toast.error(msg);
    } finally {
      setSubmitting(false);
    }
  }

  // Maps the API's `q.kind` enum to the right localised label.
  const kindKeyOf = (kind: string): MessageKey =>
    kind === "single"
      ? "quiz.kind.single"
      : kind === "short"
        ? "quiz.kind.short"
        : "quiz.kind.multi";

  return (
    <div className="space-y-6">
      {history.length > 0 && (
        <div className="rounded-md border border-gold/15 bg-card/40 p-3 font-body text-xs">
          <div className="mb-2 text-[0.62rem] uppercase tracking-[0.28em] text-gold/70">
            {t("quiz.pastAttempts", { n: history.length })}
          </div>
          <ol className="flex flex-wrap gap-2">
            {history.map((a) => (
              <li
                key={a.id}
                className={[
                  "inline-flex items-center gap-1 rounded border px-2 py-0.5 tabular-nums",
                  a.passed
                    ? "border-gold/45 bg-gold/10 text-gold"
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
          <div
            key={q.id}
            className="rounded-md border border-gold/20 bg-card/30 p-4 scroll-paper"
          >
            <div className="mb-3 flex items-start justify-between gap-2">
              <p className="font-display text-base font-medium">
                <span className="text-gold/80">{t("quiz.questionNumber", { n: idx + 1 })}</span>{" "}
                {q.prompt}
              </p>
              <div className="flex items-center gap-2">
                {submitted && (
                  <Badge
                    className={
                      questionCorrect
                        ? "border border-gold/40 bg-gold/10 text-gold"
                        : "border border-destructive/40 bg-destructive/10 text-destructive"
                    }
                  >
                    {questionCorrect ? t("quiz.correct") : t("quiz.incorrect")}
                  </Badge>
                )}
                <Badge variant="muted">{t(kindKeyOf(q.kind))}</Badge>
              </div>
            </div>
            {q.kind === "short" ? (
              <input
                type="text"
                value={typeof given === "string" ? given : ""}
                onChange={(e) => setAnswers((p) => ({ ...p, [q.id]: e.target.value }))}
                disabled={submitted}
                className="h-10 w-full rounded-md border border-gold/25 bg-background/60 px-3 font-body text-sm focus-visible:border-gold/60 focus-visible:outline-none disabled:opacity-70"
                placeholder={t("quiz.shortPlaceholder")}
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
                          "w-full rounded-md border px-3 py-2 text-start font-body text-sm transition-colors",
                          selected
                            ? "border-gold/60 bg-gold/10 text-gold"
                            : "border-border hover:border-gold/30",
                          isCorrect ? "border-gold bg-gold/15 text-gold" : "",
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
      <div className="flex items-center justify-between gap-3">
        {!submitted ? (
          <Button onClick={submit} disabled={submitting}>
            {submitting ? t("quiz.submitting") : t("quiz.submit")}
          </Button>
        ) : (
          <p
            className={`font-body text-sm ${result.passed ? "text-gold" : "text-destructive"}`}
            role="status"
          >
            {t("quiz.scoreLine", {
              pct: result.score,
              correct: result.correct_count,
              total: result.total,
            })}{" "}
            {result.passed ? t("quiz.passLine") : t("quiz.failLine", { pct: pass })}
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
            {t("quiz.retake")}
          </Button>
        )}
      </div>
    </div>
  );
}
