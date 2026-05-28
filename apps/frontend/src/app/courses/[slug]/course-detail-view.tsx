"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import Link from "next/link";
import { AlertCircle, MessageSquare } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogTitle,
} from "@/components/ui/dialog";
import { LinkButton } from "@/components/ui/link-button";
import { Skeleton } from "@/components/ui/skeleton";
import { CourseHeader } from "@/components/course/course-header";
import { CourseOutcomes } from "@/components/course/course-outcomes";
import { CourseSyllabus } from "@/components/course/course-syllabus";
import { CourseReviews } from "@/components/course/course-reviews";
import { CourseSidebar } from "@/components/course/course-sidebar";
import { TutorPanel } from "@/components/tutor/tutor-panel";
import { Courses, Me, Reviews } from "@/lib/api/endpoints";
import type { CourseDetail } from "@/lib/api/types";
import { useAuth } from "@/lib/auth/store";
import { useT } from "@/lib/i18n/provider";
import { qk } from "@/lib/query/keys";
import { useReturnFocus } from "@/lib/a11y/use-return-focus";

/**
 * Course detail page composition.
 *
 * Loop 16 decomposed this from a 444-LoC monolith into 5 local
 * components living in `@/components/course/`. This file now
 * orchestrates: load state (shape-matching Skeleton), error +
 * recovery branch, mutations, the tutor Dialog, and the PDF
 * certificate-download flow (with 401 → /login fallback).
 */
export function CourseDetailView({ slug }: { slug: string }) {
  const { user } = useAuth();
  const qc = useQueryClient();
  const router = useRouter();
  const t = useT();
  const [tutorOpen, setTutorOpen] = useState(false);
  // The tutor Dialog is controlled (no <DialogTrigger>) — capture the
  // "Ask tutor" opener on the false→true transition and restore focus
  // there on close (WCAG 2.4.3). Called unconditionally before the
  // early returns below to keep hook order stable.
  const onTutorCloseAutoFocus = useReturnFocus(tutorOpen);

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
    onError: (e: Error) =>
      toast.error(e?.message ?? t("courseDetail.enrollError")),
  });

  function handleEnroll() {
    if (!user) {
      // Loop 16: router.push instead of window.location.href so
      // scroll/auth-store state isn't dropped on full nav.
      router.push(`/login?next=${encodeURIComponent(`/courses/${slug}`)}`);
      return;
    }
    enroll.mutate();
  }

  async function handleDownloadCert() {
    if (!courseQ.data) return;
    // Loop 16: fetch the PDF via fetch (carries auth cookie),
    // handle 401 by redirecting to login, otherwise download as
    // blob. The previous bare <a href=…> rendered raw JSON if the
    // user lost their session between page-load and click.
    try {
      const res = await fetch(`/api/v1/certificates/${courseQ.data.id}.pdf`, {
        credentials: "include",
      });
      if (res.status === 401) {
        router.push(`/login?next=${encodeURIComponent(`/courses/${slug}`)}`);
        return;
      }
      if (!res.ok) {
        throw new Error(`${res.status} ${res.statusText}`);
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${courseQ.data.slug}-certificate.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t("courseDetail.certError"));
    }
  }

  // Loop 16: shape-matching skeleton replaces the plain "Loading…"
  // string. Layout matches the populated state so the page doesn't
  // jump when data lands.
  if (courseQ.isLoading) {
    return (
      <div className="container mx-auto px-6 py-10">
        <div className="grid gap-8 lg:grid-cols-[1fr_320px]">
          <div className="space-y-8">
            <header className="space-y-4">
              <Skeleton className="h-3 w-24" />
              <div className="flex gap-1.5">
                <Skeleton className="h-5 w-16" />
                <Skeleton className="h-5 w-20" />
                <Skeleton className="h-5 w-14" />
              </div>
              <Skeleton className="h-12 w-2/3" />
              <Skeleton className="h-4 w-full max-w-xl" />
              <Skeleton className="h-4 w-3/4 max-w-md" />
            </header>
            <Skeleton variant="card" className="h-32" />
            <Skeleton variant="card" className="h-64" />
          </div>
          <aside>
            <Skeleton variant="card" className="h-56" />
          </aside>
        </div>
      </div>
    );
  }

  // Loop 16: error branch with explicit recovery action — was a
  // single line of muted-foreground text; now offers "browse
  // catalog" + retry as clear next steps.
  if (courseQ.error || !courseQ.data) {
    return (
      <div className="container mx-auto flex flex-col items-center gap-4 px-6 py-20 text-center">
        <AlertCircle className="h-10 w-10 text-muted-foreground" aria-hidden />
        <h1 className="font-display text-3xl tracking-tight">
          {t("courseDetail.notFound")}
        </h1>
        <p className="max-w-md font-body text-sm text-muted-foreground">
          {t("courseDetail.notFoundBody")}
        </p>
        <div className="flex gap-2">
          <LinkButton href="/courses" variant="ghost">
            {t("courseDetail.browseCatalog")}
          </LinkButton>
          <Button variant="outline" onClick={() => courseQ.refetch()}>
            {t("common.tryAgain")}
          </Button>
        </div>
      </div>
    );
  }

  const course: CourseDetail = courseQ.data;

  return (
    <div className="container mx-auto px-6 py-10">
      <div className="grid gap-8 lg:grid-cols-[1fr_320px]">
        <div className="space-y-8">
          <CourseHeader course={course} />

          <div>
            <Link
              href={`/courses/${course.slug}/discussions`}
              className="inline-flex items-center gap-2 font-body text-sm text-foreground transition-colors duration-base hover:text-primary"
            >
              <MessageSquare className="h-4 w-4" />
              {t("course.discussionForum")}
            </Link>
          </div>

          <CourseOutcomes course={course} />

          <CourseSyllabus
            course={course}
            onAskTutor={
              course.is_enrolled ? () => setTutorOpen(true) : undefined
            }
          />

          <CourseReviews course={course} reviews={reviewsQ.data} user={user} />
        </div>

        <CourseSidebar
          course={course}
          user={user}
          onEnroll={handleEnroll}
          enrolling={enroll.isPending}
          onDownloadCert={
            course.progress_pct === 100 ? handleDownloadCert : undefined
          }
        />
      </div>

      <Dialog
        open={tutorOpen && course.is_enrolled}
        onOpenChange={setTutorOpen}
      >
        <DialogContent
          className="h-[80vh] max-w-xl overflow-hidden p-0"
          srLabelClose={t("tutor.closeButton")}
          onCloseAutoFocus={onTutorCloseAutoFocus}
        >
          <DialogTitle className="sr-only">{t("tutor.askButton")}</DialogTitle>
          <TutorPanel courseId={course.id} />
        </DialogContent>
      </Dialog>
    </div>
  );
}
