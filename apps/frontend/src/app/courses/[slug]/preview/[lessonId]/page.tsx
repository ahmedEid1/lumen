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

type Params = { slug: string; lessonId: string };

export default function PreviewLessonPage({ params }: { params: Promise<Params> }) {
  const { slug, lessonId } = use(params);

  const lessonQ = useQuery({
    queryKey: ["preview", "lesson", lessonId],
    queryFn: () => Courses.getLesson(lessonId),
    retry: false,
  });

  return (
    <div className="container mx-auto max-w-3xl px-4 py-10">
      <Link
        href={`/courses/${slug}`}
        className="mb-4 inline-flex items-center text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="mr-1 h-4 w-4" /> Back to course
      </Link>

      <Card>
        <CardHeader>
          <div className="mb-1 flex items-center gap-2">
            <Badge variant="secondary">free preview</Badge>
            {lessonQ.data && <Badge variant="muted">{lessonQ.data.type}</Badge>}
          </div>
          <CardTitle>{lessonQ.data?.title ?? "Lesson"}</CardTitle>
        </CardHeader>
        <CardContent>
          {lessonQ.isLoading ? (
            <div className="h-48 animate-pulse rounded-md bg-muted" aria-hidden />
          ) : lessonQ.error ? (
            <p className="text-sm text-muted-foreground">
              {lessonQ.error instanceof ApiError && lessonQ.error.status === 403
                ? "This lesson is for enrolled students. Enroll in the course to read it."
                : lessonQ.error instanceof ApiError && lessonQ.error.status === 404
                  ? "Lesson not found."
                  : "Could not load this preview."}
            </p>
          ) : lessonQ.data ? (
            <LessonPlayer lesson={lessonQ.data} />
          ) : null}

          <div className="mt-6 flex items-center justify-between rounded-lg border bg-muted/30 p-4">
            <p className="text-sm text-muted-foreground">
              Enjoying it? Enroll to unlock the rest of the course.
            </p>
            <Link href={`/courses/${slug}`}>
              <Button>
                <GraduationCap className="mr-1 h-4 w-4" /> Enroll
              </Button>
            </Link>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
