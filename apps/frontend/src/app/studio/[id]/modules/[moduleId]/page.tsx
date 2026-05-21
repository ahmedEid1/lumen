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
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Cartouche } from "@/components/lumen/cartouche";
import { Glyph } from "@/components/lumen/glyph";
import { Courses } from "@/lib/api/endpoints";
import { qk } from "@/lib/query/keys";
import type { LessonOut, LessonType } from "@/lib/api/types";
import { LessonEditor } from "@/components/lesson/lesson-editor";
import { useT } from "@/lib/i18n/provider";
import type { MessageKey } from "@/lib/i18n/messages/en";

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

  if (courseQ.isLoading)
    return (
      <div className="container mx-auto px-4 py-14 text-center font-body text-muted-foreground">
        {t("common.loading")}
      </div>
    );
  if (!courseQ.data || !module)
    return (
      <div className="container mx-auto flex flex-col items-center gap-3 px-4 py-20 text-center">
        <Glyph name="feather" size={48} mode="tint" className="text-gold/40" />
        <p className="font-display text-xl italic text-muted-foreground">
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
    <div className="container mx-auto px-4 py-14">
      <Link
        href={`/studio/${id}`}
        className="mb-4 inline-flex items-center font-body text-sm text-muted-foreground transition-colors hover:text-gold"
      >
        <ArrowLeft className="me-1 h-4 w-4" /> {t("moduleEdit.backToCourse")}
      </Link>
      <header className="mb-8 flex flex-col gap-3">
        <Cartouche>{t("moduleEdit.cartouche")}</Cartouche>
        <div className="text-[0.65rem] uppercase tracking-[0.28em] text-gold/70">
          {courseQ.data.title} · {t("courseDetail.module", { n: module.order + 1 })}
        </div>
        <h1 className="font-display text-4xl font-medium tracking-tight">{module.title}</h1>
        {module.description && (
          <p className="font-body text-muted-foreground">{module.description}</p>
        )}
      </header>

      <div className="grid gap-6 lg:grid-cols-[320px_1fr]">
        <Card className="scroll-paper border-gold/20">
          <CardHeader>
            <CardTitle className="font-display text-lg">{t("moduleEdit.lessons")}</CardTitle>
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

            <div className="border-t border-gold/15 pt-3">
              <p className="mb-2 text-[0.65rem] font-semibold uppercase tracking-[0.28em] text-gold/70">
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
          </CardContent>
        </Card>

        <section>
          {editing ? (
            <LessonEditor
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
              moduleId={moduleId}
              newType={creatingType}
              onSaved={() => {
                setCreatingType(null);
                qc.invalidateQueries({ queryKey: qk.course(id) });
              }}
              onCancel={() => setCreatingType(null)}
            />
          ) : (
            <Card className="scroll-paper border-gold/20">
              <CardContent className="flex flex-col items-center gap-3 py-16 text-center">
                <Glyph name="feather" size={48} mode="tint" className="text-gold/40" />
                <p className="font-body italic text-muted-foreground">{t("moduleEdit.empty")}</p>
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
        className={`flex items-center gap-2 rounded-md border bg-background/60 p-2 text-sm transition-colors ${
          selected
            ? "border-gold/60 bg-gold/10 text-gold"
            : "border-border hover:border-gold/30"
        }`}
      >
        <button
          {...attributes}
          {...listeners}
          className="cursor-grab text-muted-foreground hover:text-gold"
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
