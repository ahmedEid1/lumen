"use client";

import { use } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, GraduationCap } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { LessonPlayer } from "@/components/lesson/lesson-player";
import { ApiError } from "@/lib/api/client";
import { Courses } from "@/lib/api/endpoints";
import { useT } from "@/lib/i18n/provider";
import type { MessageKey } from "@/lib/i18n/messages/en";

type Params = { slug: string; lessonId: string };

export default function PreviewLessonPage({ params }: { params: Promise<Params> }) {
  const { slug, lessonId } = use(params);
  const t = useT();

  const lessonQ = useQuery({
    queryKey: ["preview", "lesson", lessonId],
    queryFn: () => Courses.getLesson(lessonId),
    retry: false,
  });

  const errorCopy =
    lessonQ.error instanceof ApiError && lessonQ.error.status === 403
      ? t("preview.forbidden")
      : lessonQ.error instanceof ApiError && lessonQ.error.status === 404
        ? t("preview.notFound")
        : t("preview.error");

  return (
    <div className="container mx-auto max-w-3xl px-6 py-14">
      <Link
        href={`/courses/${slug}`}
        className="mb-4 inline-flex items-center font-body text-sm text-muted-foreground transition-colors hover:text-primary"
      >
        <ArrowLeft className="me-1 h-4 w-4" /> {t("moduleEdit.backToCourse")}
      </Link>

      <div className="mb-5 flex flex-col gap-2">
        <p className="font-body text-xs font-medium uppercase tracking-[0.18em] text-primary">
          {t("preview.cartouche")}
        </p>
      </div>

      <Card className="surface">
        <CardHeader>
          <div className="mb-1 flex items-center gap-2">
            <Badge className="border border-primary/40 bg-primary/10 uppercase tracking-wider text-primary">
              {t("player.freePreview")}
            </Badge>
            {lessonQ.data && (
              <Badge variant="muted">{t(`lessonType.${lessonQ.data.type}` as MessageKey)}</Badge>
            )}
          </div>
          <CardTitle className="font-display text-3xl leading-tight tracking-tight">
            {lessonQ.data?.title ?? t("preview.lessonFallback")}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {lessonQ.isLoading ? (
            <div className="h-48 animate-pulse rounded-md border border-border/60 bg-muted" aria-hidden />
          ) : lessonQ.error ? (
            <p className="font-body text-sm text-muted-foreground">{errorCopy}</p>
          ) : lessonQ.data ? (
            <LessonPlayer lesson={lessonQ.data} />
          ) : null}

          <div className="mt-8 flex flex-col items-start justify-between gap-3 rounded-md border border-primary/30 bg-primary/5 p-4 sm:flex-row sm:items-center">
            <p className="font-body text-sm text-foreground/90">{t("preview.cta")}</p>
            <Link href={`/courses/${slug}`}>
              <Button>
                <GraduationCap className="me-1 h-4 w-4" /> {t("course.enroll")}
              </Button>
            </Link>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
