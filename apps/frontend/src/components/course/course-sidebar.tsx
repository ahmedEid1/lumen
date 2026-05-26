"use client";

import Link from "next/link";
import { Award, Layers, Star, Users } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import type { CourseDetail } from "@/lib/api/types";
import { useT } from "@/lib/i18n/provider";

type User = { id: string };

/**
 * Course detail right rail — stats grid + enroll/continue CTA +
 * download-cert link + meta footer. Extracted from
 * course-detail-view monolith in Loop 16.
 *
 * `onEnroll` and `onDownloadCert` are passed in so the parent owns
 * the network calls (mutation state, auth-error handling, router
 * navigation). The sidebar is purely presentational.
 */
export function CourseSidebar({
  course,
  user,
  onEnroll,
  enrolling,
  onDownloadCert,
}: {
  course: CourseDetail;
  user: User | null;
  onEnroll: () => void;
  enrolling: boolean;
  onDownloadCert?: () => void;
}) {
  const t = useT();
  const totalLessons = course.modules.reduce((n, m) => n + m.lessons.length, 0);
  return (
    <aside className="space-y-4">
      <Card className="bg-surface-2 lg:sticky lg:top-20">
        <CardContent className="space-y-4 pt-6">
          <div className="grid grid-cols-3 gap-2 text-center text-sm">
            <div>
              <Layers className="mx-auto h-4 w-4 text-muted-foreground" aria-hidden />
              <div className="mt-1 font-mono text-base text-foreground">
                {course.modules.length}
              </div>
              <div className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                {t("course.modules")}
              </div>
            </div>
            <div>
              <Users className="mx-auto h-4 w-4 text-muted-foreground" aria-hidden />
              <div className="mt-1 font-mono text-base text-foreground">
                {course.enrollments_count}
              </div>
              <div className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                {t("course.students")}
              </div>
            </div>
            <div>
              <Star className="mx-auto h-4 w-4 text-muted-foreground" aria-hidden />
              <div className="mt-1 font-mono text-base text-foreground">
                {course.avg_rating != null ? course.avg_rating.toFixed(1) : "—"}
              </div>
              <div className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                {t("course.rating")}
              </div>
            </div>
          </div>

          {course.is_enrolled ? (
            <div className="space-y-2">
              <div className="flex items-center justify-between font-body text-sm">
                <span className="text-muted-foreground">{t("course.progress")}</span>
                <span className="font-mono font-medium text-primary">
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
            <Button className="w-full" onClick={onEnroll} disabled={enrolling}>
              {enrolling
                ? t("courseDetail.enrolling")
                : user
                  ? t("course.enroll")
                  : t("course.signInToEnroll")}
            </Button>
          )}

          {course.progress_pct === 100 && onDownloadCert && (
            <button
              type="button"
              onClick={onDownloadCert}
              className="inline-flex w-full items-center justify-center gap-2 rounded-md border border-border bg-background px-3 py-2 font-body text-sm font-medium text-foreground transition-colors duration-base hover:bg-muted"
            >
              <Award className="h-4 w-4 text-primary" />
              {t("courseDetail.downloadCert")}
            </button>
          )}

          <p className="text-center font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
            {t("course.lessonsCount", { count: totalLessons })} ·{" "}
            {t("course.lastUpdated", {
              date: new Date(course.published_at ?? course.created_at).toLocaleDateString(),
            })}
          </p>
        </CardContent>
      </Card>
    </aside>
  );
}
