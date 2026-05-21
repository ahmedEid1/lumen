"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import Link from "next/link";
import {
  Bookmark,
  BookmarkCheck,
  Check,
  Layers,
  MessageSquare,
  Star,
  Users,
  ArrowRight,
} from "lucide-react";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Cartouche } from "@/components/lumen/cartouche";
import { Glyph } from "@/components/lumen/glyph";
import { Courses, Me, Reviews } from "@/lib/api/endpoints";
import { MyReviewEditor } from "@/components/course/my-review-editor";
import type { CourseDetail } from "@/lib/api/types";
import { useAuth } from "@/lib/auth/store";
import { useT } from "@/lib/i18n/provider";
import { qk } from "@/lib/query/keys";

export function CourseDetailView({ slug }: { slug: string }) {
  const { user } = useAuth();
  const qc = useQueryClient();
  const t = useT();

  const courseQ = useQuery({
    queryKey: qk.course(slug),
    queryFn: () => Courses.get(slug),
  });
  const reviewsQ = useQuery({
    queryKey: qk.reviews(courseQ.data?.id ?? "_"),
    queryFn: () => Reviews.list(courseQ.data!.id),
    enabled: !!courseQ.data,
  });

  const enroll = useMutation({
    mutationFn: () => Me.enroll(courseQ.data!.id),
    onSuccess: () => {
      toast.success(t("courseDetail.enrolled"));
      qc.invalidateQueries({ queryKey: qk.course(slug) });
      qc.invalidateQueries({ queryKey: qk.enrollments });
    },
    onError: (e: Error) => toast.error(e?.message ?? t("courseDetail.enrollError")),
  });

  const toggleBookmark = useMutation({
    mutationFn: () =>
      courseQ.data!.is_bookmarked ? Me.unbookmark(courseQ.data!.id) : Me.bookmark(courseQ.data!.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.course(slug) });
      qc.invalidateQueries({ queryKey: qk.bookmarks });
    },
    onError: (e: Error) => toast.error(e?.message ?? t("courseDetail.bookmarkError")),
  });

  if (courseQ.isLoading) {
    return (
      <div className="container mx-auto px-4 py-14 text-center font-body text-muted-foreground">
        {t("common.loading")}
      </div>
    );
  }
  if (courseQ.error || !courseQ.data) {
    return (
      <div className="container mx-auto flex flex-col items-center gap-3 px-4 py-20 text-center">
        <Glyph name="feather" size={48} mode="tint" className="text-gold/40" />
        <p className="font-display text-xl italic text-muted-foreground">
          {t("courseDetail.notFound")}
        </p>
      </div>
    );
  }

  const course: CourseDetail = courseQ.data;
  const totalLessons = course.modules.reduce((n, m) => n + m.lessons.length, 0);

  return (
    <div className="container mx-auto px-4 py-14">
      <div className="grid gap-10 lg:grid-cols-[1fr_320px]">
        <div className="space-y-8">
          <header className="space-y-4">
            <Cartouche>{t("courseDetail.cartouche")}</Cartouche>

            <div className="flex flex-wrap gap-2">
              <Link
                href={`/courses?subject=${encodeURIComponent(course.subject.slug)}`}
                aria-label={t("courseDetail.moreFromSubject", { name: course.subject.title })}
              >
                <Badge
                  variant="secondary"
                  className="cursor-pointer transition-colors hover:bg-secondary/80"
                >
                  {course.subject.title}
                </Badge>
              </Link>
              <Link
                href={`/courses?difficulty=${encodeURIComponent(course.difficulty)}`}
                aria-label={t("courseDetail.moreFromDifficulty", { name: course.difficulty })}
              >
                <Badge variant="muted" className="cursor-pointer hover:bg-muted/80">
                  {course.difficulty}
                </Badge>
              </Link>
              {course.tags.map((tag) => (
                <Link
                  key={tag.id}
                  href={`/courses?tag=${encodeURIComponent(tag.slug)}`}
                  aria-label={t("courseDetail.moreFromTag", { name: tag.name })}
                >
                  <Badge variant="outline" className="cursor-pointer hover:border-gold/40 hover:bg-muted">
                    {tag.name}
                  </Badge>
                </Link>
              ))}
            </div>

            <h1 className="font-display text-4xl font-medium leading-tight tracking-tight md:text-5xl">
              {course.title}
            </h1>
            <p className="max-w-2xl font-body text-lg leading-relaxed text-muted-foreground">
              {course.overview}
            </p>

            <div className="flex items-center gap-3">
              <Avatar className="border border-gold/30">
                <AvatarImage src={course.owner.avatar_url ?? undefined} alt={course.owner.full_name} />
                <AvatarFallback>{course.owner.full_name.slice(0, 1).toUpperCase()}</AvatarFallback>
              </Avatar>
              <div className="text-sm font-body">
                <div className="font-medium">{course.owner.full_name}</div>
                <div className="text-[0.7rem] uppercase tracking-[0.28em] text-gold/70">
                  {t("courseDetail.instructor")}
                </div>
              </div>
            </div>
          </header>

          <div>
            <Link
              href={`/courses/${course.slug}/discussions`}
              className="inline-flex items-center gap-2 text-sm text-gold underline-offset-4 hover:underline"
            >
              <MessageSquare className="h-4 w-4" />
              {t("course.discussionForum")}
            </Link>
          </div>

          {course.learning_outcomes && course.learning_outcomes.length > 0 && (
            <Card className="scroll-paper border-gold/20">
              <CardHeader>
                <CardTitle className="font-display text-2xl">
                  {t("course.whatYoullLearn")}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="grid gap-2.5 sm:grid-cols-2">
                  {course.learning_outcomes.map((outcome, idx) => (
                    <li key={idx} className="flex items-start gap-2 font-body text-sm">
                      <Check className="mt-0.5 h-4 w-4 shrink-0 text-gold" />
                      <span>{outcome}</span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}

          <Card className="scroll-paper border-gold/20">
            <CardHeader>
              <CardTitle className="font-display text-2xl">{t("course.syllabus")}</CardTitle>
            </CardHeader>
            <CardContent>
              {course.modules.length === 0 ? (
                <p className="font-body text-muted-foreground">{t("courseDetail.noModules")}</p>
              ) : (
                <ol className="space-y-4">
                  {course.modules.map((m) => (
                    <li
                      key={m.id}
                      className="rounded-md border border-border bg-background/40 p-4 transition-colors hover:border-gold/30"
                    >
                      <div className="mb-2">
                        <div className="text-[0.65rem] uppercase tracking-[0.28em] text-gold/70">
                          {t("courseDetail.module", { n: m.order + 1 })}
                        </div>
                        <h3 className="font-display text-lg font-medium">{m.title}</h3>
                        {m.description && (
                          <p className="font-body text-sm text-muted-foreground">{m.description}</p>
                        )}
                      </div>
                      <ul className="space-y-1 text-sm">
                        {m.lessons.map((lesson) => (
                          <li
                            key={lesson.id}
                            className="flex items-center justify-between rounded px-2 py-1 hover:bg-muted/50"
                          >
                            <span className="flex items-center gap-2 font-body">
                              <Badge variant="muted">{lesson.type}</Badge>
                              {lesson.is_preview && (
                                <Badge variant="secondary">{t("player.freePreview")}</Badge>
                              )}
                              <span
                                className={lesson.completed ? "text-muted-foreground line-through" : ""}
                              >
                                {lesson.title}
                              </span>
                              {lesson.completed && (
                                <span
                                  aria-label={t("player.completed")}
                                  title={t("player.completed")}
                                  className="text-gold"
                                >
                                  ✓
                                </span>
                              )}
                            </span>
                            <span className="flex items-center gap-3">
                              {lesson.is_preview && course.status === "published" && (
                                <Link
                                  href={`/courses/${course.slug}/preview/${lesson.id}`}
                                  className="inline-flex items-center gap-1 text-xs text-gold underline-offset-4 hover:underline"
                                >
                                  {t("courseDetail.sample")}{" "}
                                  <ArrowRight className="h-3 w-3" />
                                </Link>
                              )}
                              {lesson.duration_seconds ? (
                                <span className="text-xs text-muted-foreground">
                                  {t("courseDetail.minutes", {
                                    n: Math.round(lesson.duration_seconds / 60),
                                  })}
                                </span>
                              ) : null}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </li>
                  ))}
                </ol>
              )}
            </CardContent>
          </Card>

          <Card className="scroll-paper border-gold/20">
            <CardHeader>
              <CardTitle className="font-display text-2xl">{t("course.reviews")}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {user && course.is_enrolled && user.id !== course.owner.id && (
                <MyReviewEditor
                  courseId={course.id}
                  myReview={reviewsQ.data?.find((r) => r.author.id === user.id) ?? null}
                />
              )}
              {reviewsQ.data && reviewsQ.data.length > 0 ? (
                <ul className="space-y-4">
                  {reviewsQ.data.map((r) => (
                    <li
                      key={r.id}
                      className="rounded-md border border-border bg-background/40 p-3"
                    >
                      <div className="flex items-center gap-2 text-sm">
                        <Avatar className="h-6 w-6 border border-gold/30">
                          <AvatarImage
                            src={r.author.avatar_url ?? undefined}
                            alt={r.author.full_name}
                          />
                          <AvatarFallback>{r.author.full_name.slice(0, 1)}</AvatarFallback>
                        </Avatar>
                        <span className="font-body font-medium">{r.author.full_name}</span>
                        <span className="ms-auto inline-flex items-center gap-0.5">
                          {Array.from({ length: r.rating }).map((_, i) => (
                            <Star key={i} className="h-3.5 w-3.5 fill-gold text-gold" />
                          ))}
                        </span>
                      </div>
                      {r.body && (
                        <p className="mt-2 font-body text-sm text-muted-foreground">{r.body}</p>
                      )}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="font-body text-muted-foreground">{t("courseDetail.beFirst")}</p>
              )}
            </CardContent>
          </Card>
        </div>

        <aside className="space-y-4">
          <Card className="scroll-paper border-gold/25 lg:sticky lg:top-20">
            <CardContent className="space-y-4 pt-6">
              <div className="grid grid-cols-3 gap-2 text-center text-sm">
                <div>
                  <Layers className="mx-auto h-5 w-5 text-gold/70" />
                  <div className="mt-1 font-display text-lg">{course.modules.length}</div>
                  <div className="text-[0.65rem] uppercase tracking-wider text-muted-foreground">
                    {t("course.modules")}
                  </div>
                </div>
                <div>
                  <Users className="mx-auto h-5 w-5 text-gold/70" />
                  <div className="mt-1 font-display text-lg">{course.enrollments_count}</div>
                  <div className="text-[0.65rem] uppercase tracking-wider text-muted-foreground">
                    {t("course.students")}
                  </div>
                </div>
                <div>
                  <Star className="mx-auto h-5 w-5 text-gold/70" />
                  <div className="mt-1 font-display text-lg">
                    {course.avg_rating != null ? course.avg_rating.toFixed(1) : "—"}
                  </div>
                  <div className="text-[0.65rem] uppercase tracking-wider text-muted-foreground">
                    {t("course.rating")}
                  </div>
                </div>
              </div>

              {course.is_enrolled ? (
                <div className="space-y-2">
                  <div className="flex items-center justify-between font-body text-sm">
                    <span className="text-muted-foreground">{t("course.progress")}</span>
                    <span className="font-medium text-gold">
                      {course.progress_pct.toFixed(0)}%
                    </span>
                  </div>
                  <Progress value={course.progress_pct} />
                  <Link href={`/learn/${course.slug}`}>
                    <Button className="w-full">
                      {course.progress_pct > 0 ? t("course.continue") : t("course.start")}
                    </Button>
                  </Link>
                </div>
              ) : (
                <Button
                  className="w-full"
                  onClick={() => {
                    if (!user) {
                      window.location.href = `/login?next=${encodeURIComponent(`/courses/${course.slug}`)}`;
                      return;
                    }
                    enroll.mutate();
                  }}
                  disabled={enroll.isPending}
                >
                  {enroll.isPending
                    ? t("courseDetail.enrolling")
                    : user
                      ? t("course.enroll")
                      : t("course.signInToEnroll")}
                </Button>
              )}

              {user && (
                <Button
                  variant="outline"
                  className="w-full"
                  onClick={() => toggleBookmark.mutate()}
                  disabled={toggleBookmark.isPending}
                >
                  {course.is_bookmarked ? (
                    <>
                      <BookmarkCheck className="me-2 h-4 w-4 fill-current" />{" "}
                      {t("course.bookmarked")}
                    </>
                  ) : (
                    <>
                      <Bookmark className="me-2 h-4 w-4" /> {t("course.bookmark")}
                    </>
                  )}
                </Button>
              )}

              {course.progress_pct === 100 && (
                <a
                  href={`/api/v1/certificates/${course.id}.pdf`}
                  className="inline-flex w-full items-center justify-center gap-2 rounded-md border border-gold/40 bg-gold/5 px-3 py-2 text-sm text-gold transition-colors hover:bg-gold/10"
                >
                  <Glyph name="aten" size={16} mode="tint" />
                  {t("courseDetail.downloadCert")}
                </a>
              )}

              <p className="text-center font-body text-xs text-muted-foreground">
                {t("course.lessonsCount", { count: totalLessons })} ·{" "}
                {t("course.lastUpdated", {
                  date: new Date(course.published_at ?? course.created_at).toLocaleDateString(),
                })}
              </p>
            </CardContent>
          </Card>
        </aside>
      </div>
    </div>
  );
}
