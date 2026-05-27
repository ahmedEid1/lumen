"use client";

import { use, useState } from "react";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus, GripVertical, Settings2, Trash2 } from "lucide-react";
import {
  DndContext,
  PointerSensor,
  useSensor,
  useSensors,
  closestCenter,
  type DragEndEvent,
} from "@dnd-kit/core";
import { SortableContext, useSortable, arrayMove, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Badge } from "@/components/ui/badge";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { CohortCard } from "@/components/course/cohort-card";
import { ApiError } from "@/lib/api/client";
import { Courses } from "@/lib/api/endpoints";
import { qk } from "@/lib/query/keys";
import type { ModuleOut } from "@/lib/api/types";
import { useT, useTN } from "@/lib/i18n/provider";
import { cn } from "@/lib/utils";
import type { MessageKey } from "@/lib/i18n/messages/en";

/**
 * Studio course editor — Workbench repaint.
 *
 * Header is a left-aligned label + status badge + small toolbar of
 * actions (preview-as-student + publish/unpublish). Sections are flat
 * blocks separated by `border-t border-border` rather than nested
 * cards. Analytics tiles are mono+tabular-nums. Modules render as
 * bordered rows with a left-side drag handle and a right-side gear.
 *
 * See docs/superpowers/specs/2026-05-22-lumen-rebuild-design.md §2.
 */

const PUBLISH_REJECTION_KEYS: Record<string, MessageKey> = {
  "course.no_lessons": "studioEdit.publish.noLessons",
  "course.missing_fields": "studioEdit.publish.missingFields",
  "course.invalid_transition": "studioEdit.publish.invalidTransition",
};

export default function StudioCoursePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const qc = useQueryClient();
  const t = useT();
  const courseQ = useQuery({ queryKey: qk.course(id), queryFn: () => Courses.get(id) });
  const analyticsQ = useQuery({
    queryKey: ["course", id, "analytics"],
    queryFn: () => Courses.analytics(id),
  });
  const [newModuleTitle, setNewModuleTitle] = useState("");

  const publish = useMutation({
    mutationFn: (next: "published" | "draft" | "archived") => Courses.patch(id, { status: next }),
    onSuccess: () => {
      toast.success(t("studioEdit.statusToast"));
      qc.invalidateQueries({ queryKey: qk.course(id) });
    },
    onError: (e: Error) => {
      const code = e instanceof ApiError ? e.code : undefined;
      const keyed = code ? PUBLISH_REJECTION_KEYS[code] : undefined;
      toast.error(
        (keyed ? t(keyed) : undefined) ?? e?.message ?? t("studioEdit.statusError"),
      );
    },
  });

  const createModule = useMutation({
    mutationFn: () => Courses.createModule(id, { title: newModuleTitle }),
    onSuccess: () => {
      setNewModuleTitle("");
      qc.invalidateQueries({ queryKey: qk.course(id) });
    },
  });

  const reorder = useMutation({
    mutationFn: (modules: ModuleOut[]) =>
      Courses.reorderModules(
        id,
        Object.fromEntries(modules.map((m, i) => [m.id, i])),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.course(id) }),
  });

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }));

  if (courseQ.isLoading)
    return (
      <div className="container mx-auto px-6 py-14 font-body text-sm text-muted-foreground">
        {t("common.loading")}
      </div>
    );
  if (!courseQ.data)
    return (
      <div className="container mx-auto flex flex-col items-start gap-3 px-6 py-20">
        <p className="font-display text-xl leading-tight tracking-tight text-muted-foreground">
          {t("courseDetail.notFound")}
        </p>
      </div>
    );

  const course = courseQ.data;
  const modules = [...course.modules].sort((a, b) => a.order - b.order);

  function onDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = modules.findIndex((m) => m.id === active.id);
    const newIndex = modules.findIndex((m) => m.id === over.id);
    if (oldIndex === -1 || newIndex === -1) return;
    reorder.mutate(arrayMove(modules, oldIndex, newIndex));
  }

  return (
    <div className="container mx-auto px-6 py-14">
      <Breadcrumb className="mb-4">
        <BreadcrumbList>
          <BreadcrumbItem>
            <BreadcrumbLink asChild>
              <Link href="/studio">{t("nav.studio")}</Link>
            </BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbPage className="line-clamp-1">{course.title}</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>
      {/* Header + toolbar */}
      <header className="mb-10 flex flex-col gap-3">
        <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          {t("studioEdit.cartouche")}
        </p>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="flex flex-col gap-2">
            <Badge
              variant={
                course.status === "published"
                  ? "default"
                  : course.status === "archived"
                    ? "muted"
                    : "secondary"
              }
            >
              {t(`studio.filter.${course.status}` as MessageKey)}
            </Badge>
            <h1 className="font-display text-3xl leading-tight tracking-tight sm:text-4xl">
              {course.title}
            </h1>
            <p className="font-body text-sm text-muted-foreground">{t("studioEdit.subtitle")}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link href={`/courses/${course.slug}`} target="_blank">
              <Button variant="outline">{t("studioEdit.previewAsStudent")}</Button>
            </Link>
            {course.status !== "published" && (
              <Button onClick={() => publish.mutate("published")}>{t("studioEdit.publish")}</Button>
            )}
            {course.status === "published" && (
              <Button variant="outline" onClick={() => publish.mutate("draft")}>
                {t("studioEdit.unpublish")}
              </Button>
            )}
          </div>
        </div>
      </header>

      {/* Analytics — mono, tabular-nums, no card chrome */}
      {analyticsQ.data && (
        <section className="mb-10 border-t border-border pt-8">
          <h2 className="mb-5 font-display text-lg leading-tight tracking-tight">
            {t("studioEdit.analytics")}
          </h2>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <StatTile label={t("studioEdit.stat.enrollments")} value={analyticsQ.data.enrollments} />
            <StatTile
              label={t("studioEdit.stat.completions")}
              value={`${analyticsQ.data.completions} (${Math.round(
                analyticsQ.data.completion_rate * 100,
              )}%)`}
            />
            <StatTile
              label={t("studioEdit.stat.avgRating")}
              value={
                analyticsQ.data.avg_rating != null
                  ? `${analyticsQ.data.avg_rating.toFixed(1)} (${analyticsQ.data.rating_count})`
                  : "—"
              }
            />
            <StatTile
              label={t("studioEdit.stat.avgProgress")}
              value={`${analyticsQ.data.avg_progress_pct}%`}
            />
            <StatTile
              label={t("studioEdit.stat.new7d")}
              value={analyticsQ.data.enrollments_last_7d}
            />
            <StatTile
              label={t("studioEdit.stat.new30d")}
              value={analyticsQ.data.enrollments_last_30d}
            />
          </div>
        </section>
      )}

      {/* Cohort — keeps its existing card; aligned to the surface utility */}
      <section className="mb-10 border-t border-border pt-8">
        <CohortCard courseId={id} />
      </section>

      {/* Details */}
      <section className="mb-10 border-t border-border pt-8">
        <h2 className="mb-5 font-display text-lg leading-tight tracking-tight">
          {t("studioEdit.detailsCard")}
        </h2>
        <CourseDetailsEditor
          courseId={id}
          initial={{
            title: course.title,
            overview: course.overview,
            difficulty: course.difficulty,
            cover_url: course.cover_url ?? null,
          }}
        />
      </section>

      {/* Learning outcomes */}
      <section className="mb-10 border-t border-border pt-8">
        <h2 className="mb-5 font-display text-lg leading-tight tracking-tight">
          {t("course.whatYoullLearn")}
        </h2>
        <LearningOutcomesEditor courseId={id} initial={course.learning_outcomes ?? []} />
      </section>

      {/* Modules */}
      <section className="border-t border-border pt-8">
        <h2 className="mb-5 font-display text-lg leading-tight tracking-tight">
          {t("studioEdit.modulesCard")}
        </h2>
        <div className="mb-4 flex gap-2">
          <Input
            placeholder={t("studioEdit.newModulePlaceholder")}
            value={newModuleTitle}
            onChange={(e) => setNewModuleTitle(e.target.value)}
          />
          <Button
            onClick={() => createModule.mutate()}
            disabled={!newModuleTitle.trim() || createModule.isPending}
          >
            <Plus className="me-1 h-4 w-4" /> {t("studioEdit.addModule")}
          </Button>
        </div>

        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
          <SortableContext items={modules.map((m) => m.id)} strategy={verticalListSortingStrategy}>
            <ul className="divide-y divide-border border-y border-border">
              {modules.map((m) => (
                <SortableModule key={m.id} module={m} courseId={id} />
              ))}
            </ul>
          </SortableContext>
        </DndContext>

        <p className="mt-4 font-body text-xs text-muted-foreground">{t("studioEdit.dragTip")}</p>
      </section>
    </div>
  );
}

function SortableModule({ module: m, courseId }: { module: ModuleOut; courseId: string }) {
  const t = useT();
  const tn = useTN();
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: m.id,
  });
  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };
  return (
    <li
      ref={setNodeRef}
      style={style}
      className="flex items-center justify-between gap-3 px-1 py-3 transition-colors duration-[160ms] hover:bg-muted/30"
    >
      <div className="flex min-w-0 items-center gap-3">
        <button
          {...attributes}
          {...listeners}
          className="cursor-grab text-muted-foreground transition-colors duration-[160ms] hover:text-foreground"
          aria-label={t("studioEdit.dragHandle")}
        >
          <GripVertical className="h-4 w-4" />
        </button>
        <div className="min-w-0">
          <p className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
            {t("courseDetail.module", { n: m.order + 1 })}
          </p>
          <p className="truncate font-body text-sm font-medium text-foreground">{m.title}</p>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-3">
        <span className="font-mono text-xs tabular-nums text-muted-foreground">
          {tn("studioEdit.lessonCount", m.lessons.length)}
        </span>
        <Link
          href={`/studio/${courseId}/modules/${m.id}`}
          className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition-colors duration-[160ms] hover:bg-muted hover:text-foreground"
          aria-label={t("studioEdit.editLessons")}
        >
          <Settings2 className="h-4 w-4" />
        </Link>
      </div>
    </li>
  );
}

function StatTile({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="surface p-4">
      <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className="mt-2 font-mono text-xl tabular-nums text-foreground">{value}</p>
    </div>
  );
}

type DetailsInitial = {
  title: string;
  overview: string;
  difficulty: string;
  cover_url: string | null;
};

function CourseDetailsEditor({
  courseId,
  initial,
}: {
  courseId: string;
  initial: DetailsInitial;
}) {
  const qc = useQueryClient();
  const t = useT();
  const [draft, setDraft] = useState<DetailsInitial>(initial);
  const dirty =
    draft.title !== initial.title ||
    draft.overview !== initial.overview ||
    draft.difficulty !== initial.difficulty ||
    (draft.cover_url ?? "") !== (initial.cover_url ?? "");

  const save = useMutation({
    mutationFn: () =>
      Courses.patch(courseId, {
        title: draft.title,
        overview: draft.overview,
        difficulty: draft.difficulty,
        cover_url: draft.cover_url || null,
      }),
    onSuccess: () => {
      toast.success(t("studioEdit.detailsToast"));
      qc.invalidateQueries({ queryKey: qk.course(courseId) });
    },
    onError: (e: Error) => toast.error(e?.message ?? t("studioEdit.saveError")),
  });

  return (
    <div className="space-y-4">
      <div className="space-y-1.5">
        <label className="font-body text-sm font-medium" htmlFor="course-title-edit">
          {t("studioNew.field.title")}
        </label>
        <Input
          id="course-title-edit"
          value={draft.title}
          maxLength={200}
          onChange={(e) => setDraft({ ...draft, title: e.target.value })}
        />
        <p className="font-body text-xs text-muted-foreground">{t("studioEdit.renameNotice")}</p>
      </div>
      <div className="space-y-1.5">
        <label className="font-body text-sm font-medium" htmlFor="course-overview-edit">
          {t("studioNew.field.overview")}
        </label>
        <Textarea
          id="course-overview-edit"
          value={draft.overview}
          maxLength={10000}
          rows={4}
          onChange={(e) => setDraft({ ...draft, overview: e.target.value })}
        />
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5">
          <label className="font-body text-sm font-medium" htmlFor="course-difficulty-edit">
            {t("studioNew.field.difficulty")}
          </label>
          <Select
            value={draft.difficulty}
            onValueChange={(v) => setDraft({ ...draft, difficulty: v })}
          >
            <SelectTrigger id="course-difficulty-edit">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="beginner">{t("studioNew.diff.beginner")}</SelectItem>
              <SelectItem value="intermediate">{t("studioNew.diff.intermediate")}</SelectItem>
              <SelectItem value="advanced">{t("studioNew.diff.advanced")}</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <label className="font-body text-sm font-medium" htmlFor="course-cover-edit">
            {t("studioEdit.coverUrl")}
          </label>
          <Input
            id="course-cover-edit"
            value={draft.cover_url ?? ""}
            maxLength={500}
            onChange={(e) => setDraft({ ...draft, cover_url: e.target.value || null })}
            placeholder="https://…"
          />
        </div>
      </div>
      <Button size="sm" onClick={() => save.mutate()} disabled={!dirty || save.isPending}>
        {save.isPending ? t("common.saving") : t("common.save")}
      </Button>
    </div>
  );
}

function LearningOutcomesEditor({
  courseId,
  initial,
}: {
  courseId: string;
  initial: string[];
}) {
  const qc = useQueryClient();
  const t = useT();
  const [items, setItems] = useState<string[]>(initial);
  const dirty = JSON.stringify(items) !== JSON.stringify(initial);

  const save = useMutation({
    mutationFn: () =>
      Courses.patch(courseId, {
        learning_outcomes: items.map((s) => s.trim()).filter(Boolean),
      }),
    onSuccess: () => {
      toast.success(t("studioEdit.outcomesToast"));
      qc.invalidateQueries({ queryKey: qk.course(courseId) });
    },
    onError: (e: Error) => toast.error(e?.message ?? t("studioEdit.saveError")),
  });

  return (
    <div className="space-y-3">
      <p className="font-body text-xs text-muted-foreground">{t("studioEdit.outcomesHelp")}</p>
      <ul className="space-y-2">
        {items.map((s, i) => (
          <li key={i} className={cn("flex gap-2")}>
            <Input
              value={s}
              maxLength={240}
              onChange={(e) =>
                setItems((prev) => prev.map((v, j) => (j === i ? e.target.value : v)))
              }
              placeholder={t("studioEdit.outcomePlaceholder", { n: i + 1 })}
            />
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setItems((prev) => prev.filter((_, j) => j !== i))}
              aria-label={t("studioEdit.remove")}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </li>
        ))}
      </ul>
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={() => setItems((prev) => [...prev, ""])}
          disabled={items.length >= 12}
        >
          <Plus className="me-1 h-4 w-4" /> {t("studioEdit.addOutcome")}
        </Button>
        <Button size="sm" onClick={() => save.mutate()} disabled={!dirty || save.isPending}>
          {save.isPending ? t("common.saving") : t("common.save")}
        </Button>
      </div>
    </div>
  );
}
