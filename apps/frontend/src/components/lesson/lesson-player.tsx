"use client";

import { useState } from "react";
import type { LessonOut } from "@/lib/api/types";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { scoreQuiz, type QuizQuestion } from "@/lib/quiz";

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
          <video controls className="h-full w-full" src={String(data.url ?? "")} />
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
      return <Quiz questions={(data.questions ?? []) as QuizQuestion[]} pass={Number(data.pass_score ?? 60)} />;
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

function Quiz({ questions, pass }: { questions: QuizQuestion[]; pass: number }) {
  const [answers, setAnswers] = useState<Record<string, string[] | string>>({});
  const [submitted, setSubmitted] = useState(false);

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

  const score = submitted ? scoreQuiz(questions, answers) : null;

  return (
    <div className="space-y-6">
      {questions.map((q, idx) => {
        const given = answers[q.id];
        return (
          <div key={q.id} className="rounded-lg border p-4">
            <div className="mb-3 flex items-start justify-between gap-2">
              <p className="font-medium">
                Q{idx + 1}. {q.prompt}
              </p>
              <Badge variant="muted">{q.kind}</Badge>
            </div>
            {q.kind === "short" ? (
              <input
                type="text"
                value={typeof given === "string" ? given : ""}
                onChange={(e) => setAnswers((p) => ({ ...p, [q.id]: e.target.value }))}
                className="h-10 w-full rounded-md border bg-background px-3 text-sm"
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
                          "w-full rounded border px-3 py-2 text-left text-sm",
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
          <Button onClick={() => setSubmitted(true)}>Submit quiz</Button>
        ) : (
          <p className={`text-sm ${score! >= pass ? "text-emerald-600" : "text-destructive"}`}>
            You scored {score}%. {score! >= pass ? "Nice work!" : `Pass mark is ${pass}%. Try again.`}
          </p>
        )}
        {submitted && (
          <Button
            variant="outline"
            onClick={() => {
              setAnswers({});
              setSubmitted(false);
            }}
          >
            Retake
          </Button>
        )}
      </div>
    </div>
  );
}
