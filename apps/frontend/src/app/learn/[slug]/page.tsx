"use client";

import { use, useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
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
import { useT } from "@/lib/i18n/provider";
import { pickResumeLessonId } from "@/lib/lesson-resume";

export default function LearnPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  const { user, token, ready } = useAuth();
  const router = useRouter();
  const qc = useQueryClient();
  const t = useT();
  const courseQ = useQuery({ queryKey: qk.course(slug), queryFn: () => Courses.get(slug) });
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const lessons = useMemo(() => {
    if (!courseQ.data) return [];
    return courseQ.data.modules.flatMap((m) => m.lessons);
  }, [courseQ.data]);

  useEffect(() => {
    if (selectedId) return;
    const next = pickResumeLessonId(lessons);
    if (next) setSelectedId(next);
  }, [lessons, selectedId]);

  // Redirect visitors who aren't enrolled to the course detail page so they
  // can enroll (or preview free lessons) — the server already rejects their
  // writes, but rendering the player anyway is a confusing UX.
  useEffect(() => {
    if (!ready || !user) return;
    if (courseQ.data && courseQ.data.is_enrolled === false) {
      const ownerOrAdmin =
        user.role === "admin" || user.id === courseQ.data.owner.id;
      if (!ownerOrAdmin) {
        toast.info(t("learn.enrollToast"));
        router.replace(`/courses/${slug}`);
      }
    }
  }, [courseQ.data, ready, user, router, slug, t]);

  const selected = lessons.find((l) => l.id === selectedId) ?? null;

  if (!ready) return null;
  if (!user)
    return (
      <div className="container mx-auto flex max-w-md flex-col items-center gap-4 px-6 py-24 text-center">
        <p className="font-body text-xs font-medium uppercase tracking-[0.18em] text-primary">
          {t("learn.cartouche")}
        </p>
        <p className="font-body text-lg text-muted-foreground">{t("learn.signInPrompt")}</p>
        <Link href={`/login?next=/learn/${slug}`}>
          <Button>{t("learn.signInButton")}</Button>
        </Link>
      </div>
    );
  if (courseQ.isLoading)
    return (
      <div className="container mx-auto px-6 py-20 text-center font-body text-muted-foreground">
        {t("common.loading")}
      </div>
    );
  if (!courseQ.data)
    return (
      <div className="container mx-auto flex flex-col items-center gap-3 px-6 py-24 text-center">
        <p className="font-display text-2xl italic text-muted-foreground">
          {t("courseDetail.notFound")}
        </p>
      </div>
    );

  const course = courseQ.data;
  if (!course.is_enrolled && user.role !== "admin" && user.id !== course.owner.id) {
    // Redirect effect is firing — render nothing so we don't flash the player.
    return null;
  }

  async function complete() {
    if (!selected) return;
    try {
      await Me.markLesson(selected.id, true);
      toast.success(t("learn.markedToast"));
      qc.invalidateQueries({ queryKey: qk.course(slug) });
      qc.invalidateQueries({ queryKey: qk.enrollments });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t("learn.saveError"));
    }
  }

  return (
    <div className="container mx-auto grid gap-6 px-6 py-10 lg:grid-cols-[280px_1fr_320px]">
      {/* Outline */}
      <aside className="order-2 lg:order-none">
        <Card className="surface">
          <CardHeader>
            <p className="font-body text-xs font-medium uppercase tracking-[0.18em] text-primary">
              {t("learn.cartouche")}
            </p>
            <CardTitle className="font-display text-xl leading-tight">{course.title}</CardTitle>
            <Progress value={course.progress_pct} />
            <p className="font-body text-xs text-muted-foreground">
              {t("dashboard.percentComplete", { pct: course.progress_pct.toFixed(0) })}
            </p>
          </CardHeader>
          <CardContent className="space-y-4">
            {course.modules.map((m) => (
              <div key={m.id}>
                <div className="font-body text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
                  {t("courseDetail.module", { n: m.order + 1 })}
                </div>
                <div className="mb-2 font-display text-base">{m.title}</div>
                <ul className="space-y-0.5 text-sm">
                  {m.lessons.map((lesson) => (
                    <li key={lesson.id}>
                      <button
                        onClick={() => setSelectedId(lesson.id)}
                        className={`flex w-full items-center gap-2 rounded px-2 py-1 text-start font-body transition-colors hover:bg-muted ${
                          selectedId === lesson.id ? "bg-primary/10 text-primary" : ""
                        }`}
                      >
                        {lesson.completed ? (
                          <CheckCircle2
                            className="h-3.5 w-3.5 text-primary"
                            aria-label={t("player.completed")}
                          />
                        ) : (
                          <Circle className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
                        )}
                        <span
                          className={`truncate ${
                            lesson.completed ? "text-muted-foreground" : ""
                          }`}
                        >
                          {lesson.title}
                        </span>
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
      <section className="order-1 lg:order-none">
        {selected ? (
          <Card className="surface">
            <CardHeader>
              <CardTitle className="font-display text-4xl leading-tight tracking-tight">
                {selected.title}
              </CardTitle>
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
                    <ArrowLeft className="me-1 h-4 w-4" /> {t("player.previous")}
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
                    {t("player.next")} <ArrowRight className="ms-1 h-4 w-4" />
                  </Button>
                </div>
                <Button
                  onClick={async () => {
                    await complete();
                    const i = lessons.findIndex((l) => l.id === selected.id);
                    if (i >= 0 && i < lessons.length - 1) setSelectedId(lessons[i + 1].id);
                  }}
                >
                  <CheckCircle2 className="me-2 h-4 w-4" /> {t("player.markComplete")}
                </Button>
              </div>
            </CardContent>
          </Card>
        ) : (
          <Card className="surface">
            <CardContent className="py-16 text-center">
              <p className="font-display text-2xl italic text-muted-foreground">
                {t("learn.noLessons")}
              </p>
            </CardContent>
          </Card>
        )}
      </section>

      {/* Chat */}
      <aside className="order-3 lg:order-none">
        <Card className="surface flex h-[400px] flex-col lg:h-[600px]">
          <CardHeader className="border-b border-border/60">
            <CardTitle className="inline-flex items-center gap-2 font-display text-base">
              <MessagesSquare className="h-4 w-4 text-muted-foreground" />{" "}
              {t("learn.courseChat")}
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
