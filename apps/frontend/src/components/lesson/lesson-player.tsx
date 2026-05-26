"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import type { LessonOut, TextLessonData } from "@/lib/api/types";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Download } from "lucide-react";
import { api, ApiError } from "@/lib/api/client";
import { type QuizQuestion } from "@/lib/quiz";
import { BlockRenderer } from "@/components/lesson/block-renderer";
import { resolveTextLessonDoc } from "@/lib/lesson/blocks";
import { useT } from "@/lib/i18n/provider";
import type { MessageKey } from "@/lib/i18n/messages/en";

export function LessonPlayer({ lesson }: { lesson: LessonOut }) {
  const t = useT();
  const data = lesson.data as Record<string, any>;
  switch (lesson.type) {
    case "text":
      // BlockRenderer is the read-only counterpart to BlockEditor;
      // it walks the same JSON tree without pulling Tiptap into
      // the learner bundle. `resolveTextLessonDoc` handles both
      // the new `blocks` field and the legacy `body_markdown` /
      // `body` strings, so a course written before Phase E6 still
      // renders without a backfill.
      return <BlockRenderer value={resolveTextLessonDoc(data as TextLessonData)} />;
    case "video":
      return (
        <div className="aspect-video w-full overflow-hidden rounded-md border border-border bg-black">
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
          className="max-h-[600px] w-full rounded-md border border-border object-contain"
        />
      );
    case "file":
      return (
        <a
          href={String(data.public_url ?? "#")}
          download={String(data.filename ?? "")}
          className="inline-flex items-center gap-2 rounded-md border border-border bg-muted px-4 py-2 font-body text-sm text-foreground transition-colors duration-[160ms] hover:border-foreground/40"
        >
          <Download className="h-4 w-4" />
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
        <div className="surface p-4 font-body text-xs">
          <div className="mb-2 font-mono text-xs uppercase tracking-wider text-muted-foreground">
            {t("quiz.pastAttempts", { n: history.length })}
          </div>
          <ol className="flex flex-wrap gap-2">
            {history.map((a) => (
              <li
                key={a.id}
                className={[
                  "inline-flex items-center gap-1 rounded-sm border px-2 py-0.5 font-mono tabular-nums",
                  a.passed
                    ? "border-primary/40 bg-primary/10 text-primary"
                    : "border-border text-muted-foreground",
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
        const promptId = `${q.id}-prompt`;
        return (
          // Loop-9 a11y: each question is a <fieldset> with the
          // prompt as its <legend>. Screen readers now announce
          // "Question 3 of N, radio group, 4 options" before
          // walking the choices — the audit's heaviest a11y
          // finding (AUDIT.md §3 Block-renderer) closes here.
          <fieldset
            key={q.id}
            className="surface m-0 border-0 p-5"
            aria-labelledby={promptId}
            disabled={submitted}
          >
            <div className="mb-3 flex items-start justify-between gap-2">
              <legend id={promptId} className="font-body text-sm font-medium text-foreground">
                <span className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
                  {t("quiz.questionNumber", { n: idx + 1 })}
                </span>{" "}
                {q.prompt}
              </legend>
              <div className="flex items-center gap-2">
                {submitted && (
                  <Badge variant={questionCorrect ? "default" : "destructive"}>
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
                className="flex h-9 w-full rounded-md border border-border bg-muted px-3 py-2 font-body text-sm text-foreground transition-colors duration-base focus-visible:border-ring focus-visible:bg-background focus-visible:outline-none disabled:opacity-60"
                placeholder={t("quiz.shortPlaceholder")}
              />
            ) : q.kind === "single" ? (
              // Single-select → RadioGroup with arrow-key nav +
              // aria-checked on each item, enforced by Radix.
              <RadioGroup
                value={(given as string[] | undefined)?.[0] ?? ""}
                onValueChange={(v) => toggle(q, v)}
                disabled={submitted}
              >
                {q.choices?.map((c) => {
                  const isCorrect = submitted && q.answer_keys.includes(c.id);
                  return (
                    <RadioGroupItem
                      key={c.id}
                      value={c.id}
                      label={c.text}
                      className={
                        isCorrect ? "border-primary/60 bg-primary/10" : ""
                      }
                    />
                  );
                })}
              </RadioGroup>
            ) : (
              // Multi-select → independent checkboxes; each is its
              // own labeled input so space-to-toggle + screen-reader
              // announcement work per option.
              <ul className="flex flex-col gap-2">
                {q.choices?.map((c) => {
                  const selected = (given as string[] | undefined)?.includes(c.id) ?? false;
                  const isCorrect = submitted && q.answer_keys.includes(c.id);
                  const checkboxId = `${q.id}-${c.id}`;
                  return (
                    <li key={c.id}>
                      <label
                        htmlFor={checkboxId}
                        className={[
                          "flex w-full cursor-pointer items-start gap-3 rounded-md border px-3 py-2 text-start font-body text-sm transition-colors duration-base",
                          selected
                            ? "border-foreground/40 bg-muted text-foreground"
                            : "border-border hover:border-foreground/30",
                          isCorrect ? "border-primary/60 bg-primary/10 text-primary" : "",
                          submitted ? "cursor-not-allowed opacity-60" : "",
                        ].join(" ")}
                      >
                        <Checkbox
                          id={checkboxId}
                          checked={selected}
                          onCheckedChange={() => toggle(q, c.id)}
                          disabled={submitted}
                          className="mt-0.5"
                        />
                        <span className="flex-1">{c.text}</span>
                      </label>
                    </li>
                  );
                })}
              </ul>
            )}
          </fieldset>
        );
      })}
      <div className="flex items-center justify-between gap-3">
        {!submitted ? (
          <Button onClick={submit} disabled={submitting}>
            {submitting ? t("quiz.submitting") : t("quiz.submit")}
          </Button>
        ) : (
          <p
            className={`font-body text-sm ${result.passed ? "text-primary" : "text-destructive"}`}
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
