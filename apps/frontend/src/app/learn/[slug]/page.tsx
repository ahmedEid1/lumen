"use client";

import { use, useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  Circle,
  Sparkles,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Courses, Me } from "@/lib/api/endpoints";
import { qk } from "@/lib/query/keys";
import { LessonPlayer } from "@/components/lesson/lesson-player";
import { TutorPanel } from "@/components/tutor/tutor-panel";
import { useAuth } from "@/lib/auth/store";
import { useT } from "@/lib/i18n/provider";
import { pickResumeLessonId } from "@/lib/lesson-resume";
import { cn } from "@/lib/utils";

/**
 * Learn — Workbench repaint.
 *
 * Two-column layout: outline left (sticky, surface-1), player center on
 * the page background. Subtle module dividers; current lesson is
 * highlighted with `bg-muted border-l-2 border-foreground/40` — NOT
 * lime. Lime is reserved for the single Mark Complete CTA, and a small
 * tick on already-completed lessons.
 *
 * See docs/superpowers/specs/2026-05-22-lumen-rebuild-design.md §2.
 */
export default function LearnPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  const { user, ready } = useAuth();
  const router = useRouter();
  const qc = useQueryClient();
  const t = useT();
  const searchParams = useSearchParams();
  const courseQ = useQuery({ queryKey: qk.course(slug), queryFn: () => Courses.get(slug) });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // L20.5 — `/demo` deep-links pass `?tutor=open&q=<question>&lesson=<title-hint>`
  // so a recruiter who clicks the demo link lands with the AI tutor already
  // mounted-open + the canonical question prefilled. The lesson hint is a
  // case-insensitive substring match against lesson titles; the first match
  // wins. Honoured on mount only — later interactions belong to the user.
  const tutorParam = searchParams.get("tutor");
  const initialDraft = searchParams.get("q") ?? undefined;
  const lessonHint = searchParams.get("lesson") ?? undefined;
  const [tutorOpen, setTutorOpen] = useState(tutorParam === "open");

  const lessons = useMemo(() => {
    if (!courseQ.data) return [];
    return courseQ.data.modules.flatMap((m) => m.lessons);
  }, [courseQ.data]);

  useEffect(() => {
    if (selectedId) return;
    // L20.5 — honour the lesson hint from /demo deep-links first. Case-
    // insensitive substring match against lesson titles; fall back to
    // pickResumeLessonId so the regular learn flow is unchanged.
    if (lessonHint && lessons.length > 0) {
      const normalised = lessonHint.toLowerCase().replace(/[-_]/g, " ");
      const match = lessons.find((l) =>
        l.title.toLowerCase().includes(normalised),
      );
      if (match) {
        setSelectedId(match.id);
        return;
      }
    }
    const next = pickResumeLessonId(lessons);
    if (next) setSelectedId(next);
  }, [lessons, selectedId, lessonHint]);

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
      <div className="container mx-auto flex max-w-md flex-col items-start gap-4 px-6 py-24">
        <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          {t("learn.cartouche")}
        </p>
        <p className="font-body text-sm text-muted-foreground">{t("learn.signInPrompt")}</p>
        <Link href={`/login?next=/learn/${slug}`}>
          <Button>{t("learn.signInButton")}</Button>
        </Link>
      </div>
    );
  if (courseQ.isLoading)
    return (
      <div className="container mx-auto px-6 py-20 font-body text-sm text-muted-foreground">
        {t("common.loading")}
      </div>
    );
  if (!courseQ.data)
    return (
      <div className="container mx-auto flex flex-col items-start gap-3 px-6 py-24">
        <p className="font-display text-xl leading-tight tracking-tight text-muted-foreground">
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
    <div
      className={cn(
        "container mx-auto grid gap-6 px-6 py-10",
        tutorOpen
          ? "lg:grid-cols-[300px_1fr_360px]"
          : "lg:grid-cols-[300px_1fr]",
      )}
    >
      {/* Outline panel — surface-1, sticky on lg, subtle module dividers. */}
      <aside className="order-2 lg:order-none">
        <div className="surface lg:sticky lg:top-20">
          <div className="border-b border-border p-5">
            <p className="mb-3 font-mono text-xs uppercase tracking-wider text-muted-foreground">
              {t("learn.cartouche")}
            </p>
            <h2 className="mb-3 font-display text-base leading-tight tracking-tight">
              {course.title}
            </h2>
            <Progress value={course.progress_pct} />
            <p className="mt-2 font-mono text-xs tabular-nums text-muted-foreground">
              {t("dashboard.percentComplete", { pct: course.progress_pct.toFixed(0) })}
            </p>
          </div>
          <nav className="max-h-[70vh] overflow-y-auto">
            {course.modules.map((m, mi) => (
              <div
                key={m.id}
                className={cn("p-3", mi > 0 && "border-t border-border")}
              >
                <div className="px-2 pb-2">
                  <p className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
                    {t("courseDetail.module", { n: m.order + 1 })}
                  </p>
                  <p className="mt-0.5 font-body text-sm font-medium text-foreground">
                    {m.title}
                  </p>
                </div>
                <ul className="space-y-0.5">
                  {m.lessons.map((lesson) => {
                    const isSelected = selectedId === lesson.id;
                    return (
                      <li key={lesson.id}>
                        <button
                          onClick={() => setSelectedId(lesson.id)}
                          className={cn(
                            "flex w-full items-center gap-2 border-l-2 px-2 py-1.5 text-start font-body text-sm transition-colors duration-[160ms]",
                            isSelected
                              ? "border-foreground/40 bg-muted text-foreground"
                              : "border-transparent text-muted-foreground hover:bg-muted/40 hover:text-foreground",
                          )}
                          aria-current={isSelected ? "true" : undefined}
                        >
                          {lesson.completed ? (
                            <Check
                              className="h-3.5 w-3.5 shrink-0 text-primary"
                              aria-label={t("player.completed")}
                            />
                          ) : (
                            <Circle
                              className="h-3.5 w-3.5 shrink-0 text-muted-foreground/60"
                              aria-hidden
                            />
                          )}
                          <span className="truncate">{lesson.title}</span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))}
          </nav>
        </div>
      </aside>

      {/* Player column — page background, content carries no extra
          chrome beyond the existing media frame. */}
      <section className="order-1 min-w-0 lg:order-none">
        {selected ? (
          <>
            <div className="mb-6 flex items-start justify-between gap-3">
              <div>
                <p className="mb-2 font-mono text-xs uppercase tracking-wider text-muted-foreground">
                  {t("learn.cartouche")}
                </p>
                <h1 className="font-display text-2xl leading-tight tracking-tight sm:text-3xl">
                  {selected.title}
                </h1>
              </div>
              <Button
                variant={tutorOpen ? "default" : "outline"}
                size="sm"
                onClick={() => setTutorOpen((open) => !open)}
                aria-pressed={tutorOpen}
                aria-label={
                  tutorOpen ? t("tutor.closeButton") : t("tutor.askButton")
                }
              >
                {tutorOpen ? (
                  <X className="me-1.5 h-3.5 w-3.5" />
                ) : (
                  <Sparkles className="me-1.5 h-3.5 w-3.5" />
                )}
                {tutorOpen ? t("tutor.closeButton") : t("tutor.askButton")}
              </Button>
            </div>
            <LessonPlayer lesson={selected} />
            <div className="mt-8 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-6">
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
          </>
        ) : (
          <div className="surface flex items-center justify-center p-12">
            <p className="font-body text-sm text-muted-foreground">{t("learn.noLessons")}</p>
          </div>
        )}
      </section>

      {/* Tutor panel — unmounted until the learner toggles it on so
          the conversation isn't opened (= no LLM round-trip) before
          they actually ask.

          L24 attempted a mobile-only bottom Sheet + desktop inline
          column dual-mount, but Playwright's strict `getByTestId`
          flagged two `tutor-panel` elements (the Sheet portals to
          body regardless of viewport, so both copies sit in the DOM
          at the same time). Reverted to the single inline rendering
          here; the L24 mobile-bottom-Sheet improvement re-lands when
          we have a useMediaQuery-style mount gate that's SSR-safe.
          The L24 review-grade-buttons h-11 touch-target fix stays. */}
      {tutorOpen && (
        <aside
          className="order-3 min-w-0 lg:order-none lg:sticky lg:top-20 lg:h-[calc(100vh-7rem)]"
          aria-label={t("tutor.heading")}
        >
          <TutorPanel
            courseId={course.id}
            initialDraft={initialDraft}
            courseSlug={slug}
          />
        </aside>
      )}
    </div>
  );
}
