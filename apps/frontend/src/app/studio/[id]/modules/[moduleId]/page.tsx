"use client";

import { use, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, GripVertical } from "lucide-react";
import {
  DndContext,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  useSortable,
  arrayMove,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Courses } from "@/lib/api/endpoints";
import { qk } from "@/lib/query/keys";
import type { LessonOut, LessonType } from "@/lib/api/types";
import { LessonEditor } from "@/components/lesson/lesson-editor";

export default function ModuleEditorPage({
  params,
}: {
  params: Promise<{ id: string; moduleId: string }>;
}) {
  const { id, moduleId } = use(params);
  const qc = useQueryClient();
  const courseQ = useQuery({ queryKey: qk.course(id), queryFn: () => Courses.get(id) });

  const module = useMemo(
    () => courseQ.data?.modules.find((m) => m.id === moduleId) ?? null,
    [courseQ.data, moduleId],
  );
  const lessons = useMemo(
    () => (module ? [...module.lessons].sort((a, b) => a.order - b.order) : []),
    [module],
  );

  const [editing, setEditing] = useState<LessonOut | null>(null);
  const [creatingType, setCreatingType] = useState<LessonType | null>(null);

  const reorder = useMutation({
    mutationFn: (next: LessonOut[]) =>
      Courses.reorderLessons(moduleId, Object.fromEntries(next.map((l, i) => [l.id, i]))),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.course(id) }),
  });
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }));

  useEffect(() => {
    if (creatingType) setEditing(null);
  }, [creatingType]);

  if (courseQ.isLoading) return <div className="container mx-auto px-4 py-10">Loading…</div>;
  if (!courseQ.data || !module)
    return <div className="container mx-auto px-4 py-10">Module not found.</div>;

  function onDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = lessons.findIndex((l) => l.id === active.id);
    const newIndex = lessons.findIndex((l) => l.id === over.id);
    if (oldIndex === -1 || newIndex === -1) return;
    reorder.mutate(arrayMove(lessons, oldIndex, newIndex));
  }

  return (
    <div className="container mx-auto px-4 py-10">
      <Link
        href={`/studio/${id}`}
        className="mb-4 inline-flex items-center text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="me-1 h-4 w-4" /> Back to course
      </Link>
      <header className="mb-6">
        <div className="text-xs uppercase tracking-wide text-muted-foreground">
          {courseQ.data.title} — Module {module.order + 1}
        </div>
        <h1 className="text-3xl font-bold tracking-tight">{module.title}</h1>
        {module.description && <p className="text-muted-foreground">{module.description}</p>}
      </header>

      <div className="grid gap-6 lg:grid-cols-[320px_1fr]">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Lessons</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
              <SortableContext items={lessons.map((l) => l.id)} strategy={verticalListSortingStrategy}>
                <ul className="space-y-1.5">
                  {lessons.map((lesson) => (
                    <SortableLesson
                      key={lesson.id}
                      lesson={lesson}
                      selected={editing?.id === lesson.id}
                      onClick={() => {
                        setEditing(lesson);
                        setCreatingType(null);
                      }}
                    />
                  ))}
                </ul>
              </SortableContext>
            </DndContext>

            <div className="border-t pt-3">
              <p className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
                Add lesson
              </p>
              <div className="grid grid-cols-3 gap-1">
                {(["text", "video", "image", "file", "quiz"] as LessonType[]).map((t) => (
                  <Button
                    key={t}
                    variant="outline"
                    size="sm"
                    className="capitalize"
                    onClick={() => {
                      setCreatingType(t);
                      setEditing(null);
                    }}
                  >
                    + {t}
                  </Button>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>

        <section>
          {editing ? (
            <LessonEditor
              courseId={id}
              moduleId={moduleId}
              lesson={editing}
              onSaved={() => qc.invalidateQueries({ queryKey: qk.course(id) })}
              onDeleted={() => {
                setEditing(null);
                qc.invalidateQueries({ queryKey: qk.course(id) });
              }}
            />
          ) : creatingType ? (
            <LessonEditor
              courseId={id}
              moduleId={moduleId}
              newType={creatingType}
              onSaved={() => {
                setCreatingType(null);
                qc.invalidateQueries({ queryKey: qk.course(id) });
              }}
              onCancel={() => setCreatingType(null)}
            />
          ) : (
            <Card>
              <CardContent className="py-16 text-center text-muted-foreground">
                Pick a lesson on the left, or add a new one to start editing.
              </CardContent>
            </Card>
          )}
        </section>
      </div>
    </div>
  );
}

function SortableLesson({
  lesson,
  selected,
  onClick,
}: {
  lesson: LessonOut;
  selected: boolean;
  onClick: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: lesson.id,
  });
  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };
  return (
    <li ref={setNodeRef} style={style}>
      <div
        className={`flex items-center gap-2 rounded-md border bg-background p-2 text-sm ${
          selected ? "border-primary bg-primary/5" : ""
        }`}
      >
        <button {...attributes} {...listeners} className="cursor-grab text-muted-foreground" aria-label="Drag handle">
          <GripVertical className="h-4 w-4" />
        </button>
        <button onClick={onClick} className="flex-1 truncate text-start">
          {lesson.title}
        </button>
        <Badge variant="muted" className="capitalize">
          {lesson.type}
        </Badge>
      </div>
    </li>
  );
}
