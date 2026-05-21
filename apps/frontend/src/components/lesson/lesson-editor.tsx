"use client";

import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Courses } from "@/lib/api/endpoints";
import type { LessonOut, LessonType } from "@/lib/api/types";

type QuizChoice = { id: string; text: string };
type QuizQuestion = {
  id: string;
  prompt: string;
  kind: "single" | "multiple" | "short";
  choices: QuizChoice[];
  answer_keys: string[];
};

type Props = {
  courseId: string;
  moduleId: string;
  lesson?: LessonOut;
  newType?: LessonType;
  onSaved: () => void;
  onDeleted?: () => void;
  onCancel?: () => void;
};

export function LessonEditor({ courseId, moduleId, lesson, newType, onSaved, onDeleted, onCancel }: Props) {
  const type = (lesson?.type ?? newType ?? "text") as LessonType;
  const [title, setTitle] = useState(lesson?.title ?? "");
  const [duration, setDuration] = useState(lesson?.duration_seconds ?? 0);
  const [isPreview, setIsPreview] = useState<boolean>(lesson?.is_preview ?? false);
  const initial = useMemo(() => normalizeData(type, lesson?.data ?? {}), [type, lesson]);
  const [data, setData] = useState<any>(initial);
  const [saving, setSaving] = useState(false);

  const save = useMutation({
    mutationFn: async () => {
      const payload = {
        title,
        duration_seconds: duration || undefined,
        type,
        is_preview: isPreview,
        data: { type, ...stripType(data) },
      };
      if (lesson) {
        await Courses.patchLesson(lesson.id, {
          title: payload.title,
          duration_seconds: payload.duration_seconds,
          is_preview: payload.is_preview,
          data: payload.data,
        });
      } else {
        await Courses.createLesson(moduleId, payload);
      }
    },
    onSuccess: () => {
      toast.success("Lesson saved");
      onSaved();
    },
    onError: (e: any) => toast.error(e?.message ?? "Could not save lesson"),
  });

  const remove = useMutation({
    mutationFn: () => Courses.deleteLesson(lesson!.id),
    onSuccess: () => {
      toast.success("Lesson deleted");
      onDeleted?.();
    },
    onError: (e: any) => toast.error(e?.message ?? "Could not delete"),
  });

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>
            {lesson ? "Edit lesson" : "New lesson"} <Badge variant="muted" className="ml-2 capitalize">{type}</Badge>
          </CardTitle>
          {lesson && (
            <Button variant="ghost" size="sm" onClick={() => remove.mutate()} disabled={remove.isPending}>
              <Trash2 className="mr-1 h-4 w-4" /> Delete
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <label className="text-sm font-medium" htmlFor="title">
              Title
            </label>
            <Input id="title" value={title} onChange={(e) => setTitle(e.target.value)} required />
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium" htmlFor="duration">
              Duration (seconds)
            </label>
            <Input
              id="duration"
              type="number"
              min={0}
              value={duration}
              onChange={(e) => setDuration(Number(e.target.value) || 0)}
            />
          </div>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={isPreview}
            onChange={(e) => setIsPreview(e.target.checked)}
            className="h-4 w-4 rounded border-input"
          />
          <span>
            Free preview (visible to non-enrolled visitors when the course is published)
          </span>
        </label>

        {type === "text" && (
          <div className="space-y-1.5">
            <label className="text-sm font-medium" htmlFor="body">
              Body (Markdown)
            </label>
            <Textarea
              id="body"
              rows={14}
              value={data.body_markdown ?? ""}
              onChange={(e) => setData({ ...data, body_markdown: e.target.value })}
              placeholder="# Heading&#10;&#10;Write your lesson..."
            />
          </div>
        )}

        {type === "video" && (
          <div className="space-y-3">
            <div className="space-y-1.5">
              <label className="text-sm font-medium" htmlFor="video-url">
                Video URL
              </label>
              <Input
                id="video-url"
                value={data.url ?? ""}
                onChange={(e) => setData({ ...data, url: e.target.value })}
                placeholder="https://..."
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-sm font-medium" htmlFor="video-captions">
                Captions URL (WebVTT, optional)
              </label>
              <Input
                id="video-captions"
                value={data.captions_url ?? ""}
                onChange={(e) => setData({ ...data, captions_url: e.target.value || null })}
                placeholder="https://.../captions.vtt"
              />
              <p className="text-xs text-muted-foreground">
                Add WebVTT captions so the lesson stays accessible to deaf
                / hard-of-hearing learners. Default: on.
              </p>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <label className="text-sm font-medium" htmlFor="captions-label">
                  Caption track label
                </label>
                <Input
                  id="captions-label"
                  value={data.captions_label ?? "English"}
                  onChange={(e) => setData({ ...data, captions_label: e.target.value })}
                  placeholder="English"
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-sm font-medium" htmlFor="captions-lang">
                  Language code (BCP-47)
                </label>
                <Input
                  id="captions-lang"
                  value={data.captions_lang ?? "en"}
                  onChange={(e) => setData({ ...data, captions_lang: e.target.value })}
                  placeholder="en"
                  maxLength={10}
                />
              </div>
            </div>
          </div>
        )}

        {type === "image" && (
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label className="text-sm font-medium" htmlFor="image-key">
                Asset key
              </label>
              <Input
                id="image-key"
                value={data.asset_key ?? ""}
                onChange={(e) => setData({ ...data, asset_key: e.target.value })}
                placeholder="lesson/.../filename.jpg"
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-sm font-medium" htmlFor="image-alt">
                Alt text
              </label>
              <Input
                id="image-alt"
                value={data.alt ?? ""}
                onChange={(e) => setData({ ...data, alt: e.target.value })}
              />
            </div>
          </div>
        )}

        {type === "file" && (
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label className="text-sm font-medium" htmlFor="file-key">
                Asset key
              </label>
              <Input
                id="file-key"
                value={data.asset_key ?? ""}
                onChange={(e) => setData({ ...data, asset_key: e.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-sm font-medium" htmlFor="file-name">
                Filename
              </label>
              <Input
                id="file-name"
                value={data.filename ?? ""}
                onChange={(e) => setData({ ...data, filename: e.target.value })}
              />
            </div>
          </div>
        )}

        {type === "quiz" && <QuizEditor data={data} onChange={setData} />}
      </CardContent>
      <CardFooter className="justify-between">
        <Button onClick={() => save.mutate()} disabled={!title || save.isPending}>
          {save.isPending ? "Saving…" : "Save lesson"}
        </Button>
        {onCancel && (
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        )}
      </CardFooter>
    </Card>
  );
}

function QuizEditor({ data, onChange }: { data: any; onChange: (next: any) => void }) {
  const questions: QuizQuestion[] = data.questions ?? [];
  const passScore: number = data.pass_score ?? 60;

  function updateQ(index: number, mut: (q: QuizQuestion) => QuizQuestion) {
    const next = questions.slice();
    next[index] = mut(next[index]);
    onChange({ ...data, questions: next });
  }

  function addQ() {
    // Don't use questions.length + 1 — deleting then adding would reuse an
    // existing id, which then collides with the surviving question and
    // makes both share the same answer keys / map to the same grade slot.
    const taken = new Set(questions.map((q) => q.id));
    let n = questions.length + 1;
    while (taken.has(`q${n}`)) n += 1;
    const q: QuizQuestion = {
      id: `q${n}`,
      prompt: "",
      kind: "single",
      choices: [
        { id: "a", text: "" },
        { id: "b", text: "" },
      ],
      answer_keys: [],
    };
    onChange({ ...data, questions: [...questions, q] });
  }

  function removeQ(index: number) {
    onChange({ ...data, questions: questions.filter((_, i) => i !== index) });
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <label className="text-sm font-medium" htmlFor="pass-score">
          Pass score (%)
        </label>
        <Input
          id="pass-score"
          type="number"
          min={0}
          max={100}
          className="w-24"
          value={passScore}
          onChange={(e) => onChange({ ...data, pass_score: Number(e.target.value) || 0 })}
        />
      </div>
      <ul className="space-y-3">
        {questions.map((q, idx) => (
          <li key={idx} className="rounded-md border p-3">
            <div className="mb-2 flex items-center justify-between gap-2">
              <span className="text-xs uppercase text-muted-foreground">Question {idx + 1}</span>
              <Button variant="ghost" size="sm" onClick={() => removeQ(idx)}>
                Remove
              </Button>
            </div>
            <Input
              placeholder="Prompt"
              value={q.prompt}
              onChange={(e) => updateQ(idx, (cur) => ({ ...cur, prompt: e.target.value }))}
              className="mb-2"
            />
            <div className="mb-2 flex items-center gap-2 text-sm">
              <span>Type</span>
              <select
                className="h-9 rounded border bg-background px-2"
                value={q.kind}
                onChange={(e) =>
                  updateQ(idx, (cur) => ({
                    ...cur,
                    kind: e.target.value as QuizQuestion["kind"],
                    choices: e.target.value === "short" ? [] : cur.choices,
                    answer_keys: e.target.value === "short" ? cur.answer_keys : [],
                  }))
                }
              >
                <option value="single">Single choice</option>
                <option value="multiple">Multiple choice</option>
                <option value="short">Short answer</option>
              </select>
            </div>

            {q.kind === "short" ? (
              <Input
                placeholder="Accepted answer (case-insensitive)"
                value={q.answer_keys[0] ?? ""}
                onChange={(e) => updateQ(idx, (cur) => ({ ...cur, answer_keys: [e.target.value] }))}
              />
            ) : (
              <ul className="space-y-2">
                {q.choices.map((c, ci) => {
                  const checked = q.answer_keys.includes(c.id);
                  return (
                    <li key={ci} className="flex items-center gap-2">
                      <input
                        type={q.kind === "single" ? "radio" : "checkbox"}
                        name={`q${idx}-ans`}
                        checked={checked}
                        onChange={() =>
                          updateQ(idx, (cur) => {
                            if (cur.kind === "single") return { ...cur, answer_keys: [c.id] };
                            const set = new Set(cur.answer_keys);
                            if (checked) set.delete(c.id);
                            else set.add(c.id);
                            return { ...cur, answer_keys: Array.from(set) };
                          })
                        }
                      />
                      <Input
                        value={c.text}
                        onChange={(e) =>
                          updateQ(idx, (cur) => ({
                            ...cur,
                            choices: cur.choices.map((cc, j) =>
                              j === ci ? { ...cc, text: e.target.value } : cc,
                            ),
                          }))
                        }
                        placeholder={`Choice ${c.id.toUpperCase()}`}
                      />
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() =>
                          updateQ(idx, (cur) => ({
                            ...cur,
                            choices: cur.choices.filter((_, j) => j !== ci),
                            answer_keys: cur.answer_keys.filter((k) => k !== c.id),
                          }))
                        }
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </li>
                  );
                })}
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    updateQ(idx, (cur) => ({
                      ...cur,
                      choices: [
                        ...cur.choices,
                        { id: String.fromCharCode(97 + cur.choices.length), text: "" },
                      ],
                    }))
                  }
                >
                  <Plus className="mr-1 h-4 w-4" /> Add choice
                </Button>
              </ul>
            )}
          </li>
        ))}
      </ul>
      <Button variant="outline" onClick={addQ}>
        <Plus className="mr-1 h-4 w-4" /> Add question
      </Button>
    </div>
  );
}

function normalizeData(type: LessonType, raw: any): any {
  const copy = { ...raw };
  delete copy.type;
  switch (type) {
    case "text":
      return { body_markdown: copy.body_markdown ?? "" };
    case "video":
      return {
        url: copy.url ?? "",
        asset_key: copy.asset_key ?? null,
        captions_url: copy.captions_url ?? null,
        captions_label: copy.captions_label ?? "English",
        captions_lang: copy.captions_lang ?? "en",
      };
    case "image":
      return { asset_key: copy.asset_key ?? "", alt: copy.alt ?? "" };
    case "file":
      return { asset_key: copy.asset_key ?? "", filename: copy.filename ?? "" };
    case "quiz":
      return {
        pass_score: copy.pass_score ?? 60,
        questions: Array.isArray(copy.questions) ? copy.questions : [],
      };
  }
}

function stripType(obj: any) {
  const { type, ...rest } = obj;
  return rest;
}
