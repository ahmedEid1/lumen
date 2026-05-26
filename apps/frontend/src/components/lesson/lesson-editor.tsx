"use client";

import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus, Sparkles, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { AI, Courses } from "@/lib/api/endpoints";
import type { LessonOut, LessonType, TextLessonData } from "@/lib/api/types";
import { BlockEditor } from "@/components/lesson/block-editor";
import { resolveTextLessonDoc, type BlockDoc, isBlockDoc, emptyDoc } from "@/lib/lesson/blocks";
import { useT } from "@/lib/i18n/provider";
import type { MessageKey } from "@/lib/i18n/messages/en";

type QuizChoice = { id: string; text: string };
type QuizQuestion = {
  id: string;
  prompt: string;
  kind: "single" | "multiple" | "short";
  choices: QuizChoice[];
  answer_keys: string[];
};

type Props = {
  moduleId: string;
  /** Optional — only used to feed the "course context" to the AI assist
   *  buttons. The lesson editor stays usable without it (the AI calls
   *  just send an empty context string). */
  courseId?: string;
  courseTitle?: string;
  lesson?: LessonOut;
  newType?: LessonType;
  onSaved: () => void;
  onDeleted?: () => void;
  onCancel?: () => void;
};

export function LessonEditor({
  moduleId,
  courseId: _courseId,
  courseTitle,
  lesson,
  newType,
  onSaved,
  onDeleted,
  onCancel,
}: Props) {
  const t = useT();
  const type = (lesson?.type ?? newType ?? "text") as LessonType;
  const [title, setTitle] = useState(lesson?.title ?? "");
  const [duration, setDuration] = useState(lesson?.duration_seconds ?? 0);
  const [isPreview, setIsPreview] = useState<boolean>(lesson?.is_preview ?? false);
  const initial = useMemo(() => normalizeData(type, lesson?.data ?? {}), [type, lesson]);
  const [data, setData] = useState<any>(initial);
  const [aiBusy, setAiBusy] = useState(false);

  async function draftBodyWithAi() {
    if (!title.trim()) {
      toast.error(t("lessonEdit.ai.needTitle"));
      return;
    }
    setAiBusy(true);
    try {
      const res = await AI.lessonBody({
        lesson_title: title.trim(),
        course_context: courseTitle ?? "",
      });
      const blocks = isBlockDoc(res.blocks) ? res.blocks : emptyDoc();
      setData((prev: any) => ({ ...prev, blocks }));
      toast.success(t("lessonEdit.ai.bodyDraftedToast"));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t("lessonEdit.ai.error"));
    } finally {
      setAiBusy(false);
    }
  }

  async function generateQuizWithAi() {
    if (!title.trim()) {
      toast.error(t("lessonEdit.ai.needTitle"));
      return;
    }
    setAiBusy(true);
    try {
      const res = await AI.quiz({
        lesson_title: title.trim(),
        course_context: courseTitle ?? "",
        n: 4,
      });
      setData((prev: any) => ({
        ...prev,
        questions: res.questions,
      }));
      toast.success(t("lessonEdit.ai.quizDraftedToast"));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t("lessonEdit.ai.error"));
    } finally {
      setAiBusy(false);
    }
  }

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
      toast.success(t("lessonEdit.savedToast"));
      onSaved();
    },
    onError: (e: Error) => toast.error(e?.message ?? t("lessonEdit.saveError")),
  });

  const remove = useMutation({
    mutationFn: () => Courses.deleteLesson(lesson!.id),
    onSuccess: () => {
      toast.success(t("lessonEdit.deletedToast"));
      onDeleted?.();
    },
    onError: (e: Error) => toast.error(e?.message ?? t("lessonEdit.deleteError")),
  });

  return (
    <Card className="surface">
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="font-display text-2xl">
            {lesson ? t("lessonEdit.titleEdit") : t("lessonEdit.titleNew")}{" "}
            <Badge variant="muted" className="ms-2">
              {t(`lessonType.${type}` as MessageKey)}
            </Badge>
          </CardTitle>
          {lesson && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => remove.mutate()}
              disabled={remove.isPending}
              className="text-muted-foreground hover:text-destructive"
            >
              <Trash2 className="me-1 h-4 w-4" /> {t("common.delete")}
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <label className="font-body text-sm font-medium" htmlFor="title">
              {t("studioNew.field.title")}
            </label>
            <Input id="title" value={title} onChange={(e) => setTitle(e.target.value)} required />
          </div>
          <div className="space-y-1.5">
            <label className="font-body text-sm font-medium" htmlFor="duration">
              {t("lessonEdit.duration")}
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
        <div className="flex items-center gap-2 font-body text-sm">
          <Switch
            id="lesson-free-preview"
            checked={isPreview}
            onCheckedChange={setIsPreview}
          />
          <label htmlFor="lesson-free-preview">{t("lessonEdit.freePreview")}</label>
        </div>

        {type === "text" && (
          <div className="space-y-1.5">
            <div className="flex items-center justify-between gap-2">
              <label className="font-body text-sm font-medium" id="lesson-body-label">
                {t("lessonEdit.body")}
              </label>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={draftBodyWithAi}
                disabled={aiBusy || !title.trim()}
                aria-label={t("lessonEdit.ai.draftBody")}
              >
                <Sparkles className="me-1 h-3.5 w-3.5" />
                {aiBusy ? t("lessonEdit.ai.drafting") : t("lessonEdit.ai.draftBody")}
              </Button>
            </div>
            <div aria-labelledby="lesson-body-label">
              <BlockEditor
                value={data.blocks as BlockDoc}
                onChange={(blocks) => setData({ ...data, blocks })}
                placeholder={t("lessonEdit.bodyPlaceholder")}
              />
            </div>
          </div>
        )}

        {type === "video" && (
          <div className="space-y-3">
            <div className="space-y-1.5">
              <label className="font-body text-sm font-medium" htmlFor="video-url">
                {t("lessonEdit.videoUrl")}
              </label>
              <Input
                id="video-url"
                value={data.url ?? ""}
                onChange={(e) => setData({ ...data, url: e.target.value })}
                placeholder="https://..."
              />
            </div>
            <div className="space-y-1.5">
              <label className="font-body text-sm font-medium" htmlFor="video-captions">
                {t("lessonEdit.captionsUrl")}
              </label>
              <Input
                id="video-captions"
                value={data.captions_url ?? ""}
                onChange={(e) => setData({ ...data, captions_url: e.target.value || null })}
                placeholder="https://.../captions.vtt"
              />
              <p className="font-body text-xs text-muted-foreground">
                {t("lessonEdit.captionsHelp")}
              </p>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <label className="font-body text-sm font-medium" htmlFor="captions-label">
                  {t("lessonEdit.captionsLabel")}
                </label>
                <Input
                  id="captions-label"
                  // Persisted data fallback intentionally stays as the
                  // literal "English" — it's what the <track label="">
                  // attribute shows to learners on the video player if
                  // the instructor doesn't override it. The placeholder
                  // is the only locale-aware part: an Arabic instructor
                  // sees "العربية" as the hint, suggesting they should
                  // type the language they're actually using.
                  value={data.captions_label ?? "English"}
                  onChange={(e) => setData({ ...data, captions_label: e.target.value })}
                  placeholder={t("lessonEdit.captionsLabelPlaceholder")}
                />
              </div>
              <div className="space-y-1.5">
                <label className="font-body text-sm font-medium" htmlFor="captions-lang">
                  {t("lessonEdit.captionsLang")}
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
              <label className="font-body text-sm font-medium" htmlFor="image-key">
                {t("lessonEdit.assetKey")}
              </label>
              <Input
                id="image-key"
                value={data.asset_key ?? ""}
                onChange={(e) => setData({ ...data, asset_key: e.target.value })}
                placeholder="lesson/.../filename.jpg"
              />
            </div>
            <div className="space-y-1.5">
              <label className="font-body text-sm font-medium" htmlFor="image-alt">
                {t("lessonEdit.altText")}
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
              <label className="font-body text-sm font-medium" htmlFor="file-key">
                {t("lessonEdit.assetKey")}
              </label>
              <Input
                id="file-key"
                value={data.asset_key ?? ""}
                onChange={(e) => setData({ ...data, asset_key: e.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <label className="font-body text-sm font-medium" htmlFor="file-name">
                {t("lessonEdit.filename")}
              </label>
              <Input
                id="file-name"
                value={data.filename ?? ""}
                onChange={(e) => setData({ ...data, filename: e.target.value })}
              />
            </div>
          </div>
        )}

        {type === "quiz" && (
          <div className="space-y-3">
            <div className="flex justify-end">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={generateQuizWithAi}
                disabled={aiBusy || !title.trim()}
                aria-label={t("lessonEdit.ai.generateQuiz")}
              >
                <Sparkles className="me-1 h-3.5 w-3.5" />
                {aiBusy ? t("lessonEdit.ai.drafting") : t("lessonEdit.ai.generateQuiz")}
              </Button>
            </div>
            <QuizEditor data={data} onChange={setData} />
          </div>
        )}
      </CardContent>
      <CardFooter className="justify-between">
        <Button onClick={() => save.mutate()} disabled={!title || save.isPending}>
          {save.isPending ? t("common.saving") : t("lessonEdit.save")}
        </Button>
        {onCancel && (
          <Button variant="ghost" onClick={onCancel}>
            {t("common.cancel")}
          </Button>
        )}
      </CardFooter>
    </Card>
  );
}

function QuizEditor({ data, onChange }: { data: any; onChange: (next: any) => void }) {
  const t = useT();
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
        <label className="font-body text-sm font-medium" htmlFor="pass-score">
          {t("quizEdit.passScore")}
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
          <li key={idx} className="surface p-4">
            <div className="mb-2 flex items-center justify-between gap-2">
              <span className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
                {t("quizEdit.questionN", { n: idx + 1 })}
              </span>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => removeQ(idx)}
                className="text-muted-foreground hover:text-destructive"
              >
                {t("studioEdit.remove")}
              </Button>
            </div>
            <Input
              placeholder={t("quizEdit.promptPlaceholder")}
              value={q.prompt}
              onChange={(e) => updateQ(idx, (cur) => ({ ...cur, prompt: e.target.value }))}
              className="mb-2"
            />
            <div className="mb-2 flex items-center gap-2 font-body text-sm">
              <span>{t("quizEdit.type")}</span>
              <Select
                value={q.kind}
                onValueChange={(v) =>
                  updateQ(idx, (cur) => ({
                    ...cur,
                    kind: v as QuizQuestion["kind"],
                    choices: v === "short" ? [] : cur.choices,
                    answer_keys: v === "short" ? cur.answer_keys : [],
                  }))
                }
              >
                <SelectTrigger
                  aria-label={t("quizEdit.type")}
                  className="h-9 w-auto min-w-[10rem]"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="single">{t("quizEdit.kindSingle")}</SelectItem>
                  <SelectItem value="multiple">{t("quizEdit.kindMulti")}</SelectItem>
                  <SelectItem value="short">{t("quizEdit.kindShort")}</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {q.kind === "short" ? (
              <Input
                placeholder={t("quizEdit.shortAnswerPlaceholder")}
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
                        className="accent-[hsl(var(--primary))]"
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
                        placeholder={t("quizEdit.choicePlaceholder", { letter: c.id.toUpperCase() })}
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
                        className="text-muted-foreground hover:text-destructive"
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
                  <Plus className="me-1 h-4 w-4" /> {t("quizEdit.addChoice")}
                </Button>
              </ul>
            )}
          </li>
        ))}
      </ul>
      <Button variant="outline" onClick={addQ}>
        <Plus className="me-1 h-4 w-4" /> {t("quizEdit.addQuestion")}
      </Button>
    </div>
  );
}

function normalizeData(type: LessonType, raw: any): any {
  const copy = { ...raw };
  delete copy.type;
  switch (type) {
    case "text":
      // Promote whichever shape arrived from the wire into the new
      // block-tree form. Legacy lessons stored markdown in
      // `body_markdown`; the block editor (Phase E6) writes
      // `blocks` and is the only field the player reads going
      // forward. The promotion is lossless for new lessons (the
      // doc round-trips through Tiptap unchanged) and best-effort
      // for legacy ones (markdown → single paragraph; see
      // `lib/lesson/blocks.ts`).
      return { blocks: resolveTextLessonDoc(copy as TextLessonData) };
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
  const { type: _type, ...rest } = obj;
  return rest;
}
