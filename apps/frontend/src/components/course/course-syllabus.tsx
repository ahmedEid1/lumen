"use client";

import Link from "next/link";
import { ArrowRight, Check, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { CourseDetail } from "@/lib/api/types";
import { useT } from "@/lib/i18n/provider";
import { cn } from "@/lib/utils";

/**
 * Course syllabus — module + lesson breakdown. Includes the "Ask
 * tutor" CTA in the header (only rendered for enrolled users —
 * `onAskTutor` is optional and the caller toggles visibility).
 * Extracted from course-detail-view monolith in Loop 16.
 */
export function CourseSyllabus({
  course,
  onAskTutor,
}: {
  course: CourseDetail;
  onAskTutor?: () => void;
}) {
  const t = useT();
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <CardTitle className="font-display text-xl leading-tight">
          {t("course.syllabus")}
        </CardTitle>
        {onAskTutor && (
          <Button
            variant="outline"
            size="sm"
            onClick={onAskTutor}
            aria-label={t("tutor.askButton")}
          >
            <Sparkles className="me-1.5 h-3.5 w-3.5" />
            {t("tutor.askButton")}
          </Button>
        )}
      </CardHeader>
      <CardContent>
        {course.modules.length === 0 ? (
          <p className="font-body text-sm text-muted-foreground">
            {t("courseDetail.noModules")}
          </p>
        ) : (
          <ol className="divide-y divide-border">
            {course.modules.map((m) => (
              <li key={m.id} className="py-4 first:pt-0 last:pb-0">
                <div className="mb-2">
                  <div className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
                    {t("courseDetail.module", { n: m.order + 1 })}
                  </div>
                  <h3 className="break-words font-display text-base leading-tight">
                    {m.title}
                  </h3>
                  {m.description && (
                    <p className="mt-1 break-words font-body text-sm text-muted-foreground">
                      {m.description}
                    </p>
                  )}
                </div>
                <ul className="divide-y divide-border/60 text-sm">
                  {m.lessons.map((lesson) => (
                    <li
                      key={lesson.id}
                      className="flex items-center justify-between gap-3 py-2"
                    >
                      <span className="flex min-w-0 items-center gap-2 font-body">
                        {lesson.completed ? (
                          <Check
                            aria-label={t("player.completed")}
                            className="h-4 w-4 shrink-0 text-primary"
                          />
                        ) : (
                          <span
                            aria-hidden
                            className="inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-border"
                          />
                        )}
                        <Badge variant="muted" className="font-mono">
                          {lesson.type}
                        </Badge>
                        {lesson.is_preview && (
                          <Badge variant="default" className="font-mono">
                            {t("player.freePreview")}
                          </Badge>
                        )}
                        <span
                          className={cn(
                            "truncate font-body",
                            lesson.completed && "text-muted-foreground",
                          )}
                        >
                          {lesson.title}
                        </span>
                      </span>
                      <span className="flex shrink-0 items-center gap-3">
                        {lesson.is_preview && course.status === "published" && (
                          <Link
                            href={`/courses/${course.slug}/preview/${lesson.id}`}
                            className="inline-flex items-center gap-1 font-body text-xs font-medium text-primary hover:underline"
                          >
                            {t("courseDetail.sample")} <ArrowRight className="h-3 w-3" />
                          </Link>
                        )}
                        {lesson.duration_seconds ? (
                          <span className="font-mono text-xs text-muted-foreground">
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
  );
}
