"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Sparkles, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { AI, Catalog, Courses } from "@/lib/api/endpoints";
import type {
  CourseOutline,
  OutlineLesson,
  OutlineModule,
} from "@/lib/api/endpoints";
import { qk } from "@/lib/query/keys";
import { useT } from "@/lib/i18n/provider";
import { cn } from "@/lib/utils";
import type { MessageKey } from "@/lib/i18n/messages/en";

/**
 * AI outline generator — Studio entry point for Phase E2.
 *
 * Three states inside one modal:
 *   1. "brief"   — instructor types a 1-2 paragraph description.
 *   2. "review"  — the proposed outline renders as an editable tree.
 *                  Inline rename per row, delete per row, delete per
 *                  module. No drag-reorder yet (the API accepts any
 *                  ordering at commit time; reorder can be added with
 *                  dnd-kit later if instructors ask for it).
 *   3. "creating"— "Create draft course" is in flight: create the
 *                  course shell, then commit the outline against it,
 *                  then navigate to /studio/{course_id}.
 *
 * Why the two-step flow. The user-facing promise of this modal is
 * "nothing lands in your account until you click Create". Generate is
 * a preview, not a save. The instructor edits the preview as much as
 * they want before committing. Only on commit does the API write
 * anything to the DB — and even then the course stays in draft, with
 * placeholder lesson bodies the instructor will overwrite per-lesson.
 *
 * See ``docs/superpowers/specs/2026-05-22-lumen-rebuild-design.md`` §4
 * Phase E item 2.
 */

type Phase = "brief" | "review" | "creating";

export function AIOutlineModal({ onClose }: { onClose: () => void }) {
  const t = useT();
  const router = useRouter();
  const subjectsQ = useQuery({ queryKey: qk.subjects, queryFn: () => Catalog.subjects() });
  const [phase, setPhase] = useState<Phase>("brief");
  const [brief, setBrief] = useState("");
  const [targetModules, setTargetModules] = useState(4);
  const [generating, setGenerating] = useState(false);
  const [outline, setOutline] = useState<CourseOutline | null>(null);

  async function handleGenerate() {
    if (!brief.trim()) return;
    setGenerating(true);
    try {
      const result = await AI.outline({ brief: brief.trim(), target_modules: targetModules });
      setOutline(result);
      setPhase("review");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t("ai.outline.error"));
    } finally {
      setGenerating(false);
    }
  }

  async function handleCreate() {
    if (!outline) return;
    const firstSubject = subjectsQ.data?.[0];
    if (!firstSubject) {
      toast.error(t("ai.outline.noSubject"));
      return;
    }
    setPhase("creating");
    try {
      // 1. Create an empty draft course so commit-outline has a target.
      const course = await Courses.create({
        title: outline.title,
        subject_id: firstSubject.id,
        overview: outline.overview,
        difficulty: "beginner",
      });
      // 2. Persist the (possibly-edited) outline against it.
      await AI.commitOutline({ course_id: course.id, outline });
      toast.success(t("ai.outline.createdToast"));
      onClose();
      router.push(`/studio/${course.id}`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t("ai.outline.createError"));
      setPhase("review");
    }
  }

  const lessonCount = useMemo(
    () => outline?.modules.reduce((acc, m) => acc + m.lessons.length, 0) ?? 0,
    [outline],
  );

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent
        className="flex max-h-[90vh] w-full max-w-3xl flex-col gap-4 overflow-hidden p-6 sm:p-8"
        srLabelClose={t("common.cancel")}
      >
        <DialogHeader>
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-muted-foreground" />
            <DialogTitle className="font-display text-2xl tracking-tight">
              {t("ai.outline.title")}
            </DialogTitle>
          </div>
          {/* Wire the dialog's accessible description (Radix warns when
              DialogContent has none). Replaces the brief-phase <p>. */}
          <DialogDescription className="font-body text-sm text-muted-foreground">
            {t("ai.outline.subtitle")}
          </DialogDescription>
        </DialogHeader>

        {phase === "brief" && (
          <div className="flex flex-col gap-4">
            <div className="space-y-1.5">
              <label className="font-body text-sm font-medium" htmlFor="ai-brief">
                {t("ai.outline.briefLabel")}
              </label>
              <Textarea
                id="ai-brief"
                rows={6}
                value={brief}
                onChange={(e) => setBrief(e.target.value)}
                placeholder={t("ai.outline.briefPlaceholder")}
              />
            </div>
            <div className="space-y-1.5">
              <label className="font-body text-sm font-medium" htmlFor="ai-modules">
                {t("ai.outline.modulesLabel")}
              </label>
              <Input
                id="ai-modules"
                type="number"
                min={2}
                max={8}
                value={targetModules}
                onChange={(e) =>
                  setTargetModules(Math.max(2, Math.min(8, Number(e.target.value) || 4)))
                }
                className="w-24"
              />
            </div>
            <div className="flex justify-end pt-1">
              <Button onClick={handleGenerate} disabled={!brief.trim() || generating}>
                <Sparkles className="me-2 h-4 w-4" />
                {generating ? t("ai.outline.generating") : t("ai.outline.generate")}
              </Button>
            </div>
          </div>
        )}

        {(phase === "review" || phase === "creating") && outline && (
          <div className="flex flex-col gap-4 overflow-hidden">
            <div className="flex flex-col gap-2">
              <div className="space-y-1.5">
                <label className="font-body text-sm font-medium" htmlFor="ai-title">
                  {t("ai.outline.courseTitle")}
                </label>
                <Input
                  id="ai-title"
                  value={outline.title}
                  onChange={(e) =>
                    setOutline({ ...outline, title: e.target.value })
                  }
                />
              </div>
              <div className="space-y-1.5">
                <label className="font-body text-sm font-medium" htmlFor="ai-overview">
                  {t("ai.outline.courseOverview")}
                </label>
                <Textarea
                  id="ai-overview"
                  rows={3}
                  value={outline.overview}
                  onChange={(e) =>
                    setOutline({ ...outline, overview: e.target.value })
                  }
                />
              </div>
            </div>

            <div className="flex items-center justify-between gap-2 border-t border-border pt-3">
              <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
                {t("ai.outline.moduleHeader", {
                  modules: outline.modules.length,
                  lessons: lessonCount,
                })}
              </p>
            </div>

            <div
              data-testid="ai-outline-preview"
              className="flex flex-col gap-3 overflow-y-auto pr-1"
              style={{ maxHeight: "40vh" }}
            >
              {outline.modules.map((mod, mi) => (
                <ModuleRow
                  key={mi}
                  module={mod}
                  index={mi}
                  onRenameModule={(title) =>
                    setOutline((cur) =>
                      cur
                        ? {
                            ...cur,
                            modules: cur.modules.map((m, i) =>
                              i === mi ? { ...m, title } : m,
                            ),
                          }
                        : cur,
                    )
                  }
                  onDeleteModule={() =>
                    setOutline((cur) =>
                      cur
                        ? {
                            ...cur,
                            modules: cur.modules.filter((_, i) => i !== mi),
                          }
                        : cur,
                    )
                  }
                  onRenameLesson={(li, title) =>
                    setOutline((cur) =>
                      cur
                        ? {
                            ...cur,
                            modules: cur.modules.map((m, i) =>
                              i === mi
                                ? {
                                    ...m,
                                    lessons: m.lessons.map((l, j) =>
                                      j === li ? { ...l, title } : l,
                                    ),
                                  }
                                : m,
                            ),
                          }
                        : cur,
                    )
                  }
                  onDeleteLesson={(li) =>
                    setOutline((cur) =>
                      cur
                        ? {
                            ...cur,
                            modules: cur.modules.map((m, i) =>
                              i === mi
                                ? {
                                    ...m,
                                    lessons: m.lessons.filter((_, j) => j !== li),
                                  }
                                : m,
                            ),
                          }
                        : cur,
                    )
                  }
                />
              ))}
              {outline.modules.length === 0 && (
                <p className="font-body text-sm text-muted-foreground">
                  {t("ai.outline.emptyModules")}
                </p>
              )}
            </div>

            <div className="flex items-center justify-between gap-2 border-t border-border pt-3">
              <Button
                variant="outline"
                onClick={() => {
                  setOutline(null);
                  setPhase("brief");
                }}
                disabled={phase === "creating"}
              >
                {t("ai.outline.startOver")}
              </Button>
              <Button
                onClick={handleCreate}
                disabled={
                  phase === "creating" ||
                  outline.modules.length === 0 ||
                  !outline.title.trim()
                }
              >
                {phase === "creating"
                  ? t("ai.outline.creating")
                  : t("ai.outline.create")}
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function ModuleRow({
  module,
  index,
  onRenameModule,
  onDeleteModule,
  onRenameLesson,
  onDeleteLesson,
}: {
  module: OutlineModule;
  index: number;
  onRenameModule: (title: string) => void;
  onDeleteModule: () => void;
  onRenameLesson: (lessonIndex: number, title: string) => void;
  onDeleteLesson: (lessonIndex: number) => void;
}) {
  const t = useT();
  return (
    <div className="rounded-md border border-border bg-card/50 p-3">
      <div className="mb-2 flex items-center gap-2">
        <span className="font-mono text-xs tabular-nums text-muted-foreground">
          {String(index + 1).padStart(2, "0")}
        </span>
        <Input
          value={module.title}
          onChange={(e) => onRenameModule(e.target.value)}
          className="font-display"
          aria-label={t("ai.outline.moduleTitleAria", { n: index + 1 })}
        />
        <Button
          variant="ghost"
          size="icon"
          onClick={onDeleteModule}
          className="text-muted-foreground hover:text-destructive"
          aria-label={t("ai.outline.deleteModuleAria", { n: index + 1 })}
        >
          <Trash2 className="h-4 w-4" />
        </Button>
      </div>
      <ul className="ms-6 space-y-1">
        {module.lessons.map((lesson, li) => (
          <LessonRow
            key={li}
            lesson={lesson}
            onRename={(title) => onRenameLesson(li, title)}
            onDelete={() => onDeleteLesson(li)}
          />
        ))}
        {module.lessons.length === 0 && (
          <li className="font-body text-xs text-muted-foreground">
            {t("ai.outline.emptyLessons")}
          </li>
        )}
      </ul>
    </div>
  );
}

function LessonRow({
  lesson,
  onRename,
  onDelete,
}: {
  lesson: OutlineLesson;
  onRename: (title: string) => void;
  onDelete: () => void;
}) {
  const t = useT();
  const typeKey: MessageKey = `lessonType.${lesson.type}`;
  return (
    <li className={cn("flex items-center gap-2")}>
      <Input
        value={lesson.title}
        onChange={(e) => onRename(e.target.value)}
        className="h-8"
      />
      <Badge variant="muted">{t(typeKey)}</Badge>
      <Button
        variant="ghost"
        size="icon"
        onClick={onDelete}
        className="text-muted-foreground hover:text-destructive"
        aria-label={t("ai.outline.deleteLessonAria")}
      >
        <Trash2 className="h-4 w-4" />
      </Button>
    </li>
  );
}
