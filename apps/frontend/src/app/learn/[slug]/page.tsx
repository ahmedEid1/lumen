"use client";

import { use, useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { toast } from "sonner";
import { ArrowLeft, ArrowRight, CheckCircle2, Circle, MessagesSquare } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Courses, Me } from "@/lib/api/endpoints";
import { qk } from "@/lib/query/keys";
import { LessonPlayer } from "@/components/lesson/lesson-player";
import { ChatRoom } from "@/components/chat/chat-room";
import { useAuth } from "@/lib/auth/store";

export default function LearnPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  const { user, token, ready } = useAuth();
  const qc = useQueryClient();
  const courseQ = useQuery({ queryKey: qk.course(slug), queryFn: () => Courses.get(slug) });
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const lessons = useMemo(() => {
    if (!courseQ.data) return [];
    return courseQ.data.modules.flatMap((m) => m.lessons);
  }, [courseQ.data]);

  useEffect(() => {
    if (!selectedId && lessons.length > 0) setSelectedId(lessons[0].id);
  }, [lessons, selectedId]);

  const selected = lessons.find((l) => l.id === selectedId) ?? null;

  if (!ready) return null;
  if (!user)
    return (
      <div className="container mx-auto px-4 py-10">
        Please <Link className="text-primary underline" href={`/login?next=/learn/${slug}`}>sign in</Link> to learn.
      </div>
    );
  if (courseQ.isLoading) return <div className="container mx-auto px-4 py-10">Loading…</div>;
  if (!courseQ.data)
    return <div className="container mx-auto px-4 py-10 text-muted-foreground">Course not found.</div>;

  const course = courseQ.data;

  async function complete() {
    if (!selected) return;
    try {
      await Me.markLesson(selected.id, true);
      toast.success("Marked complete");
      qc.invalidateQueries({ queryKey: qk.course(slug) });
      qc.invalidateQueries({ queryKey: qk.enrollments });
    } catch (e: any) {
      toast.error(e?.message ?? "Could not save");
    }
  }

  return (
    <div className="container mx-auto grid gap-6 px-4 py-6 lg:grid-cols-[280px_1fr_320px]">
      {/* Outline */}
      <aside>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{course.title}</CardTitle>
            <Progress value={course.progress_pct} />
            <p className="text-xs text-muted-foreground">{course.progress_pct.toFixed(0)}% complete</p>
          </CardHeader>
          <CardContent className="space-y-4">
            {course.modules.map((m) => (
              <div key={m.id}>
                <div className="text-xs uppercase tracking-wide text-muted-foreground">
                  Module {m.order + 1}
                </div>
                <div className="mb-2 font-medium">{m.title}</div>
                <ul className="space-y-0.5 text-sm">
                  {m.lessons.map((lesson) => (
                    <li key={lesson.id}>
                      <button
                        onClick={() => setSelectedId(lesson.id)}
                        className={`flex w-full items-center gap-2 rounded px-2 py-1 text-left hover:bg-muted ${
                          selectedId === lesson.id ? "bg-muted" : ""
                        }`}
                      >
                        <Circle className="h-3.5 w-3.5 text-muted-foreground" />
                        <span className="truncate">{lesson.title}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </CardContent>
        </Card>
      </aside>

      {/* Player */}
      <section>
        {selected ? (
          <Card>
            <CardHeader>
              <CardTitle>{selected.title}</CardTitle>
            </CardHeader>
            <CardContent>
              <LessonPlayer lesson={selected} />
              <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    onClick={() => {
                      const i = lessons.findIndex((l) => l.id === selected.id);
                      if (i > 0) setSelectedId(lessons[i - 1].id);
                    }}
                    disabled={lessons.findIndex((l) => l.id === selected.id) <= 0}
                  >
                    <ArrowLeft className="mr-1 h-4 w-4" /> Previous
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => {
                      const i = lessons.findIndex((l) => l.id === selected.id);
                      if (i >= 0 && i < lessons.length - 1) setSelectedId(lessons[i + 1].id);
                    }}
                    disabled={
                      lessons.findIndex((l) => l.id === selected.id) >= lessons.length - 1
                    }
                  >
                    Next <ArrowRight className="ml-1 h-4 w-4" />
                  </Button>
                </div>
                <Button
                  onClick={async () => {
                    await complete();
                    const i = lessons.findIndex((l) => l.id === selected.id);
                    if (i >= 0 && i < lessons.length - 1) setSelectedId(lessons[i + 1].id);
                  }}
                >
                  <CheckCircle2 className="mr-2 h-4 w-4" /> Mark complete &amp; continue
                </Button>
              </div>
            </CardContent>
          </Card>
        ) : (
          <Card>
            <CardContent className="py-10 text-center text-muted-foreground">
              No lessons in this course yet.
            </CardContent>
          </Card>
        )}
      </section>

      {/* Chat */}
      <aside>
        <Card className="flex h-[600px] flex-col">
          <CardHeader className="border-b">
            <CardTitle className="inline-flex items-center gap-2 text-base">
              <MessagesSquare className="h-4 w-4" /> Course chat
            </CardTitle>
          </CardHeader>
          <CardContent className="flex-1 overflow-hidden p-0">
            <ChatRoom courseId={course.id} token={token} />
          </CardContent>
        </Card>
      </aside>
    </div>
  );
}
