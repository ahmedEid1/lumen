"use client";

import { use, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, GripVertical, Plus } from "lucide-react";
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
import { Courses } from "@/lib/api/endpoints";
import { qk } from "@/lib/query/keys";
import type { LessonOut, LessonType } from "@/lib/api/types";
import { LessonEditor } from "@/components/lesson/lesson-editor";
import { useT } from "@/lib/i18n/provider";
import { cn } from "@/lib/utils";
import type { MessageKey } from "@/lib/i18n/messages/en";

/**
 * Module / lesson editor — Workbench repaint.
 *
 * Two columns: left sidebar (surface-1) lists lessons as compact rows
 * with a drag handle + lesson-type badge; bottom of the sidebar has the
 * type-specific create buttons. Right column hosts the lesson editor —
 * the form sits on `surface` inside `lesson-editor.tsx` already.
 *
 * See docs/superpowers/specs/2026-05-22-lumen-rebuild-design.md §2.
 */

const LESSON_TYPES: { value: LessonType; key: MessageKey }[] = [
  { value: "text", key: "lessonType.text" },
  { value: "video", key: "lessonType.video" },
  { value: "image", key: "lessonType.image" },
  { value: "file", key: "lessonType.file" },
  { value: "quiz", key: "lessonType.quiz" },
];

export default function ModuleEditorPage({
  params,
}: {
  params: Promise<{ id: string; moduleId: string }>;
}) {
  const { id, moduleId } = use(params);
  const qc = useQueryClient();
  const t = useT();
  const courseQ = useQuery({ queryKey: qk.course(id), queryFn: () => Courses.get(id) });

  const activeModule = useMemo(
    () => courseQ.data?.modules.find((m) => m.id === moduleId) ?? null,
    [courseQ.data, moduleId],
  );
  const lessons = useMemo(
    () =>
      activeModule ? [...activeModule.lessons].sort((a, b) => a.order - b.order) : [],
    [activeModule],
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

  if (courseQ.isLoading)
    return (
      <div className="container mx-auto px-6 py-14 font-body text-sm text-muted-foreground">
        {t("common.loading")}
      </div>
    );
  if (!courseQ.data || !activeModule)
    return (
      <div className="container mx-auto flex flex-col items-start gap-3 px-6 py-20">
        <p className="font-display text-xl leading-tight tracking-tight text-muted-foreground">
          {t("moduleEdit.notFound")}
        </p>
      </div>
    );

  function onDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = lessons.findIndex((l) => l.id === active.id);
    const newIndex = lessons.findIndex((l) => l.id === over.id);
    if (oldIndex === -1 || newIndex === -1) return;
    reorder.mutate(arrayMove(lessons, oldIndex, newIndex));
  }

  return (
    <div className="container mx-auto px-6 py-14">
      <Link
        href={`/studio/${id}`}
        className="mb-4 inline-flex items-center font-body text-sm text-muted-foreground transition-colors duration-[160ms] hover:text-foreground"
      >
        <ArrowLeft className="me-1 h-4 w-4" /> {t("moduleEdit.backToCourse")}
      </Link>
      <header className="mb-8 flex flex-col gap-3">
        <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          {t("moduleEdit.cartouche")}
        </p>
        <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          {courseQ.data.title} · {t("courseDetail.module", { n: activeModule.order + 1 })}
        </p>
        <h1 className="font-display text-3xl leading-tight tracking-tight sm:text-4xl">
          {activeModule.title}
        </h1>
        {activeModule.description && (
          <p className="font-body text-sm text-muted-foreground">{activeModule.description}</p>
        )}
      </header>

      <div className="grid gap-6 lg:grid-cols-[300px_1fr]">
        <aside className="surface lg:sticky lg:top-20 lg:self-start">
          <div className="border-b border-border p-4">
            <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
              {t("moduleEdit.lessons")}
            </p>
          </div>
          <div className="p-2">
            <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
              <SortableContext items={lessons.map((l) => l.id)} strategy={verticalListSortingStrategy}>
                <ul className="space-y-1">
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
          </div>

          <div className="border-t border-border p-4">
            <p className="mb-2 font-mono text-xs uppercase tracking-wider text-muted-foreground">
              {t("moduleEdit.addLesson")}
            </p>
            <div className="grid grid-cols-3 gap-1">
              {LESSON_TYPES.map(({ value, key }) => (
                <Button
                  key={value}
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setCreatingType(value);
                    setEditing(null);
                  }}
                >
                  <Plus className="me-1 h-3 w-3" /> {t(key)}
                </Button>
              ))}
            </div>
          </div>
        </aside>

        <section className="min-w-0">
          {editing ? (
            <LessonEditor
              moduleId={moduleId}
              courseId={id}
              courseTitle={courseQ.data?.title}
              lesson={editing}
              onSaved={() => qc.invalidateQueries({ queryKey: qk.course(id) })}
              onDeleted={() => {
                setEditing(null);
                qc.invalidateQueries({ queryKey: qk.course(id) });
              }}
            />
          ) : creatingType ? (
            <LessonEditor
              moduleId={moduleId}
              courseId={id}
              courseTitle={courseQ.data?.title}
              newType={creatingType}
              onSaved={() => {
                setCreatingType(null);
                qc.invalidateQueries({ queryKey: qk.course(id) });
              }}
              onCancel={() => setCreatingType(null)}
            />
          ) : (
            <div className="surface flex items-center justify-center p-12">
              <p className="font-body text-sm text-muted-foreground">{t("moduleEdit.empty")}</p>
            </div>
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
  const t = useT();
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: lesson.id,
  });
  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };
  const typeKey = `lessonType.${lesson.type}` as MessageKey;
  return (
    <li ref={setNodeRef} style={style}>
      <div
        className={cn(
          "flex items-center gap-2 rounded-md border-l-2 px-2 py-1.5 text-sm transition-colors duration-[160ms]",
          selected
            ? "border-foreground/40 bg-muted text-foreground"
            : "border-transparent text-muted-foreground hover:bg-muted/40 hover:text-foreground",
        )}
      >
        <button
          {...attributes}
          {...listeners}
          className="cursor-grab text-muted-foreground transition-colors duration-[160ms] hover:text-foreground"
          aria-label={t("studioEdit.dragHandle")}
        >
          <GripVertical className="h-4 w-4" />
        </button>
        <button onClick={onClick} className="flex-1 truncate text-start font-body">
          {lesson.title}
        </button>
        <Badge variant="muted">{t(typeKey)}</Badge>
      </div>
    </li>
  );
}
