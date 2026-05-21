"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import Link from "next/link";
import { Bookmark, BookmarkCheck, Layers, Star, Users, Award } from "lucide-react";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Courses, Me, Reviews } from "@/lib/api/endpoints";
import { MyReviewEditor } from "@/components/course/my-review-editor";
import type { CourseDetail } from "@/lib/api/types";
import { useAuth } from "@/lib/auth/store";
import { qk } from "@/lib/query/keys";

export function CourseDetailView({ slug }: { slug: string }) {
  const { user } = useAuth();
  const qc = useQueryClient();

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
      toast.success("Enrolled!");
      qc.invalidateQueries({ queryKey: qk.course(slug) });
      qc.invalidateQueries({ queryKey: qk.enrollments });
    },
    onError: (e: any) => toast.error(e?.message ?? "Could not enroll"),
  });

  const toggleBookmark = useMutation({
    mutationFn: () =>
      courseQ.data!.is_bookmarked ? Me.unbookmark(courseQ.data!.id) : Me.bookmark(courseQ.data!.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.course(slug) });
      qc.invalidateQueries({ queryKey: qk.bookmarks });
    },
    onError: (e: any) => toast.error(e?.message ?? "Could not update bookmark"),
  });

  if (courseQ.isLoading) {
    return <div className="container mx-auto px-4 py-10">Loading…</div>;
  }
  if (courseQ.error || !courseQ.data) {
    return (
      <div className="container mx-auto px-4 py-10 text-center text-muted-foreground">
        Course not found.
      </div>
    );
  }

  const course: CourseDetail = courseQ.data;
  const totalLessons = course.modules.reduce((n, m) => n + m.lessons.length, 0);

  return (
    <div className="container mx-auto px-4 py-10">
      <div className="grid gap-8 lg:grid-cols-[1fr_320px]">
        <div className="space-y-6">
          <div>
            <div className="mb-2 flex flex-wrap gap-2">
              <Link
                href={`/courses?subject=${encodeURIComponent(course.subject.slug)}`}
                aria-label={`More ${course.subject.title} courses`}
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
                aria-label={`More ${course.difficulty} courses`}
              >
                <Badge variant="muted" className="cursor-pointer hover:bg-muted/80">
                  {course.difficulty}
                </Badge>
              </Link>
              {course.tags.map((t) => (
                <Link
                  key={t.id}
                  href={`/courses?tag=${encodeURIComponent(t.slug)}`}
                  aria-label={`More ${t.name} courses`}
                >
                  <Badge variant="outline" className="cursor-pointer hover:bg-muted">
                    {t.name}
                  </Badge>
                </Link>
              ))}
            </div>
            <h1 className="text-3xl font-bold tracking-tight md:text-4xl">{course.title}</h1>
            <p className="mt-3 max-w-2xl text-muted-foreground">{course.overview}</p>
            <div className="mt-4 flex items-center gap-3">
              <Avatar>
                <AvatarImage src={course.owner.avatar_url ?? undefined} alt={course.owner.full_name} />
                <AvatarFallback>{course.owner.full_name.slice(0, 1).toUpperCase()}</AvatarFallback>
              </Avatar>
              <div className="text-sm">
                <div className="font-medium">{course.owner.full_name}</div>
                <div className="text-muted-foreground">Instructor</div>
              </div>
            </div>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Syllabus</CardTitle>
            </CardHeader>
            <CardContent>
              {course.modules.length === 0 ? (
                <p className="text-muted-foreground">No modules yet.</p>
              ) : (
                <ol className="space-y-4">
                  {course.modules.map((m) => (
                    <li key={m.id} className="rounded-lg border p-4">
                      <div className="mb-2">
                        <div className="text-xs uppercase tracking-wide text-muted-foreground">
                          Module {m.order + 1}
                        </div>
                        <h3 className="font-semibold">{m.title}</h3>
                        {m.description && (
                          <p className="text-sm text-muted-foreground">{m.description}</p>
                        )}
                      </div>
                      <ul className="space-y-1 text-sm">
                        {m.lessons.map((lesson) => (
                          <li
                            key={lesson.id}
                            className="flex items-center justify-between rounded px-2 py-1 hover:bg-muted/50"
                          >
                            <span className="flex items-center gap-2">
                              <Badge variant="muted">{lesson.type}</Badge>
                              {lesson.is_preview && <Badge variant="secondary">free preview</Badge>}
                              <span
                                className={lesson.completed ? "text-muted-foreground line-through" : ""}
                              >
                                {lesson.title}
                              </span>
                              {lesson.completed && (
                                <span
                                  aria-label="completed"
                                  title="Completed"
                                  className="text-emerald-600 dark:text-emerald-400"
                                >
                                  ✓
                                </span>
                              )}
                            </span>
                            <span className="flex items-center gap-3">
                              {lesson.is_preview && course.status === "published" && (
                                <Link
                                  href={`/courses/${course.slug}/preview/${lesson.id}`}
                                  className="text-xs text-primary hover:underline"
                                >
                                  Sample →
                                </Link>
                              )}
                              {lesson.duration_seconds ? (
                                <span className="text-xs text-muted-foreground">
                                  {Math.round(lesson.duration_seconds / 60)} min
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

          <Card>
            <CardHeader>
              <CardTitle>Reviews</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {user && course.is_enrolled && user.id !== course.owner.id && (
                // Owners can self-enroll to preview, but the backend rejects
                // self-reviews — don't render a button that always 403s.
                <MyReviewEditor
                  courseId={course.id}
                  myReview={reviewsQ.data?.find((r) => r.author.id === user.id) ?? null}
                />
              )}
              {reviewsQ.data && reviewsQ.data.length > 0 ? (
                <ul className="space-y-4">
                  {reviewsQ.data.map((r) => (
                    <li key={r.id} className="rounded border p-3">
                      <div className="flex items-center gap-2 text-sm">
                        <Avatar className="h-6 w-6">
                          <AvatarImage src={r.author.avatar_url ?? undefined} alt={r.author.full_name} />
                          <AvatarFallback>{r.author.full_name.slice(0, 1)}</AvatarFallback>
                        </Avatar>
                        <span className="font-medium">{r.author.full_name}</span>
                        <span className="ml-auto inline-flex items-center gap-0.5">
                          {Array.from({ length: r.rating }).map((_, i) => (
                            <Star key={i} className="h-3.5 w-3.5 fill-current text-amber-500" />
                          ))}
                        </span>
                      </div>
                      {r.body && <p className="mt-2 text-sm text-muted-foreground">{r.body}</p>}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-muted-foreground">Be the first to review this course.</p>
              )}
            </CardContent>
          </Card>
        </div>

        <aside className="space-y-4">
          <Card>
            <CardContent className="space-y-3 pt-6">
              <div className="grid grid-cols-3 gap-2 text-center text-sm">
                <div>
                  <Layers className="mx-auto h-5 w-5 text-muted-foreground" />
                  <div className="mt-1 font-semibold">{course.modules.length}</div>
                  <div className="text-xs text-muted-foreground">Modules</div>
                </div>
                <div>
                  <Users className="mx-auto h-5 w-5 text-muted-foreground" />
                  <div className="mt-1 font-semibold">{course.enrollments_count}</div>
                  <div className="text-xs text-muted-foreground">Students</div>
                </div>
                <div>
                  <Star className="mx-auto h-5 w-5 text-muted-foreground" />
                  <div className="mt-1 font-semibold">
                    {course.avg_rating != null ? course.avg_rating.toFixed(1) : "—"}
                  </div>
                  <div className="text-xs text-muted-foreground">Rating</div>
                </div>
              </div>

              {course.is_enrolled ? (
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">Progress</span>
                    <span className="font-medium">{course.progress_pct.toFixed(0)}%</span>
                  </div>
                  <Progress value={course.progress_pct} />
                  <Link href={`/learn/${course.slug}`}>
                    <Button className="w-full">
                      {course.progress_pct > 0 ? "Continue learning" : "Start learning"}
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
                  {enroll.isPending ? "Enrolling…" : user ? "Enroll" : "Sign in to enroll"}
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
                      <BookmarkCheck className="mr-2 h-4 w-4 fill-current" /> Bookmarked
                    </>
                  ) : (
                    <>
                      <Bookmark className="mr-2 h-4 w-4" /> Bookmark
                    </>
                  )}
                </Button>
              )}

              {course.progress_pct === 100 && (
                <a
                  href={`/api/v1/certificates/${course.id}.pdf`}
                  className="inline-flex w-full items-center justify-center gap-2 rounded-md border px-3 py-2 text-sm hover:bg-muted"
                >
                  <Award className="h-4 w-4" /> Download certificate
                </a>
              )}

              <p className="text-center text-xs text-muted-foreground">
                {totalLessons} lessons · last updated{" "}
                {new Date(course.published_at ?? course.created_at).toLocaleDateString()}
              </p>
            </CardContent>
          </Card>
        </aside>
      </div>
    </div>
  );
}
