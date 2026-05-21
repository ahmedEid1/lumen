"use client";

import { use, useState } from "react";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus, GripVertical, Settings2 } from "lucide-react";
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
  });

  const duplicate = useMutation({
    mutationFn: () => Courses.duplicate(id),
    onSuccess: (c) => {
      toast.success("Course duplicated");
      qc.invalidateQueries({ queryKey: qk.myCourses });
      window.location.href = `/studio/${c.id}`;
    },
    onError: (e: any) => toast.error(e?.message ?? "Could not duplicate"),
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
              <Plus className="mr-1 h-4 w-4" /> Add module
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
