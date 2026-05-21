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
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { CohortCard } from "@/components/course/cohort-card";
import { ApiError } from "@/lib/api/client";
import { Courses } from "@/lib/api/endpoints";
import { qk } from "@/lib/query/keys";
import type { ModuleOut } from "@/lib/api/types";

export default function StudioCoursePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const qc = useQueryClient();
  const courseQ = useQuery({ queryKey: qk.course(id), queryFn: () => Courses.get(id) });
  const analyticsQ = useQuery({
    queryKey: ["course", id, "analytics"],
    queryFn: () => Courses.analytics(id),
  });
  const [newModuleTitle, setNewModuleTitle] = useState("");

  const publish = useMutation({
    mutationFn: (next: "published" | "draft" | "archived") => Courses.patch(id, { status: next }),
    onSuccess: () => {
      toast.success("Status updated");
      qc.invalidateQueries({ queryKey: qk.course(id) });
    },
    onError: (e: Error) => {
      // Server can refuse the transition for a few reasons (missing
      // fields, invalid transition, no lessons). Without this toast the
      // instructor would see no feedback at all and assume the click
      // didn't register.
      const code = e instanceof ApiError ? e.code : undefined;
      if (code === "course.no_lessons") {
        toast.error("Add at least one lesson before publishing.");
      } else if (code === "course.missing_fields") {
        toast.error("A title and overview are required to publish.");
      } else if (code === "course.invalid_transition") {
        toast.error("That status change isn't allowed from the current state.");
      } else {
        toast.error(e?.message ?? "Could not update status");
      }
    },
  });

  const duplicate = useMutation({
    mutationFn: () => Courses.duplicate(id),
    onSuccess: (c) => {
      toast.success("Course duplicated");
      qc.invalidateQueries({ queryKey: qk.myCourses });
      window.location.href = `/studio/${c.id}`;
    },
    onError: (e: Error) => toast.error(e?.message ?? "Could not duplicate"),
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

  if (courseQ.isLoading) return <div className="container mx-auto px-4 py-10">Loading…</div>;
  if (!courseQ.data) return <div className="container mx-auto px-4 py-10">Course not found.</div>;

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
    <div className="container mx-auto px-4 py-10">
      <header className="mb-6 flex items-center justify-between">
        <div>
          <Badge variant={course.status === "published" ? "default" : "muted"}>{course.status}</Badge>
          <h1 className="mt-1 text-3xl font-bold tracking-tight">{course.title}</h1>
          <p className="text-muted-foreground">Manage modules and lessons.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link href={`/courses/${course.slug}`} target="_blank">
            <Button variant="outline">Preview as student</Button>
          </Link>
          <Button variant="outline" onClick={() => duplicate.mutate()} disabled={duplicate.isPending}>
            {duplicate.isPending ? "Duplicating…" : "Duplicate"}
          </Button>
          {course.status !== "published" && (
            <Button onClick={() => publish.mutate("published")}>Publish</Button>
          )}
          {course.status === "published" && (
            <Button variant="outline" onClick={() => publish.mutate("draft")}>
              Unpublish
            </Button>
          )}
        </div>
      </header>

      {analyticsQ.data && (
        <Card className="mb-6">
          <CardHeader>
            <CardTitle>Analytics</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
              <StatTile label="Enrollments" value={analyticsQ.data.enrollments} />
              <StatTile
                label="Completions"
                value={`${analyticsQ.data.completions} (${Math.round(
                  analyticsQ.data.completion_rate * 100,
                )}%)`}
              />
              <StatTile
                label="Avg rating"
                value={
                  analyticsQ.data.avg_rating != null
                    ? `${analyticsQ.data.avg_rating.toFixed(1)} (${analyticsQ.data.rating_count})`
                    : "—"
                }
              />
              <StatTile label="Avg progress" value={`${analyticsQ.data.avg_progress_pct}%`} />
              <StatTile label="New (7d)" value={analyticsQ.data.enrollments_last_7d} />
              <StatTile label="New (30d)" value={analyticsQ.data.enrollments_last_30d} />
            </div>
          </CardContent>
        </Card>
      )}

      <div className="mb-6">
        <CohortCard courseId={id} />
      </div>

      <Card className="mb-6">
        <CardHeader>
          <CardTitle>Course details</CardTitle>
        </CardHeader>
        <CardContent>
          <CourseDetailsEditor
            courseId={id}
            initial={{
              title: course.title,
              overview: course.overview,
              difficulty: course.difficulty,
              cover_url: course.cover_url ?? null,
            }}
          />
        </CardContent>
      </Card>

      <Card className="mb-6">
        <CardHeader>
          <CardTitle>What you&apos;ll learn</CardTitle>
        </CardHeader>
        <CardContent>
          <LearningOutcomesEditor
            courseId={id}
            initial={course.learning_outcomes ?? []}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Modules</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex gap-2">
            <Input
              placeholder="New module title"
              value={newModuleTitle}
              onChange={(e) => setNewModuleTitle(e.target.value)}
            />
            <Button
              onClick={() => createModule.mutate()}
              disabled={!newModuleTitle.trim() || createModule.isPending}
            >
              <Plus className="me-1 h-4 w-4" /> Add module
            </Button>
          </div>

          <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
            <SortableContext items={modules.map((m) => m.id)} strategy={verticalListSortingStrategy}>
              <ul className="space-y-2">
                {modules.map((m) => (
                  <SortableModule key={m.id} module={m} courseId={id} />
                ))}
              </ul>
            </SortableContext>
          </DndContext>
        </CardContent>
      </Card>

      <p className="mt-6 text-xs text-muted-foreground">
        Tip: drag the handle to reorder modules. Click the gear to edit a module&apos;s lessons.
      </p>
    </div>
  );
}

function SortableModule({ module: m, courseId }: { module: ModuleOut; courseId: string }) {
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
      className="flex items-center justify-between rounded-md border bg-background p-3"
    >
      <div className="flex items-center gap-3">
        <button {...attributes} {...listeners} className="cursor-grab" aria-label="Drag handle">
          <GripVertical className="h-4 w-4 text-muted-foreground" />
        </button>
        <div>
          <div className="text-xs text-muted-foreground">Module {m.order + 1}</div>
          <div className="font-medium">{m.title}</div>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <Badge variant="muted">{m.lessons.length} lessons</Badge>
        <Link
          href={`/studio/${courseId}/modules/${m.id}`}
          className="inline-flex h-8 w-8 items-center justify-center rounded-md hover:bg-muted"
          aria-label="Edit lessons"
        >
          <Settings2 className="h-4 w-4 text-muted-foreground" />
        </Link>
      </div>
    </li>
  );
}

function StatTile({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-md border bg-background p-3">
      <div className="text-xs uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
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
      toast.success("Details saved");
      qc.invalidateQueries({ queryKey: qk.course(courseId) });
    },
    onError: (e: Error) => toast.error(e?.message ?? "Could not save"),
  });

  return (
    <div className="space-y-4">
      <div className="space-y-1.5">
        <label className="text-sm font-medium" htmlFor="course-title-edit">
          Title
        </label>
        <Input
          id="course-title-edit"
          value={draft.title}
          maxLength={200}
          onChange={(e) => setDraft({ ...draft, title: e.target.value })}
        />
        <p className="text-xs text-muted-foreground">
          Renaming regenerates the URL slug — old links to this course
          will redirect.
        </p>
      </div>
      <div className="space-y-1.5">
        <label className="text-sm font-medium" htmlFor="course-overview-edit">
          Overview
        </label>
        <textarea
          id="course-overview-edit"
          value={draft.overview}
          maxLength={10000}
          rows={4}
          onChange={(e) => setDraft({ ...draft, overview: e.target.value })}
          className="w-full rounded-md border bg-background px-3 py-2 text-sm"
        />
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5">
          <label className="text-sm font-medium" htmlFor="course-difficulty-edit">
            Difficulty
          </label>
          <select
            id="course-difficulty-edit"
            value={draft.difficulty}
            onChange={(e) => setDraft({ ...draft, difficulty: e.target.value })}
            className="h-10 w-full rounded-md border bg-background px-3 text-sm"
          >
            <option value="beginner">Beginner</option>
            <option value="intermediate">Intermediate</option>
            <option value="advanced">Advanced</option>
          </select>
        </div>
        <div className="space-y-1.5">
          <label className="text-sm font-medium" htmlFor="course-cover-edit">
            Cover URL
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
        {save.isPending ? "Saving…" : "Save"}
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
  const [items, setItems] = useState<string[]>(initial);
  const dirty = JSON.stringify(items) !== JSON.stringify(initial);

  const save = useMutation({
    mutationFn: () =>
      Courses.patch(courseId, {
        learning_outcomes: items.map((s) => s.trim()).filter(Boolean),
      }),
    onSuccess: () => {
      toast.success("Outcomes saved");
      qc.invalidateQueries({ queryKey: qk.course(courseId) });
    },
    onError: (e: Error) => toast.error(e?.message ?? "Could not save"),
  });

  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">
        Up to 12 short phrases (each ≤240 chars). Shows above the syllabus
        on the course detail page as a checkmark grid.
      </p>
      <ul className="space-y-2">
        {items.map((s, i) => (
          <li key={i} className="flex gap-2">
            <Input
              value={s}
              maxLength={240}
              onChange={(e) => {
                const next = [...items];
                next[i] = e.target.value;
                setItems(next);
              }}
              placeholder={`Outcome #${i + 1}`}
            />
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setItems(items.filter((_, j) => j !== i))}
              aria-label="Remove"
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
          onClick={() => setItems([...items, ""])}
          disabled={items.length >= 12}
        >
          <Plus className="me-1 h-4 w-4" /> Add outcome
        </Button>
        <Button size="sm" onClick={() => save.mutate()} disabled={!dirty || save.isPending}>
          {save.isPending ? "Saving…" : "Save"}
        </Button>
      </div>
    </div>
  );
}
