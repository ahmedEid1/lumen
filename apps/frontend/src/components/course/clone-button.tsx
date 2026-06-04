"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { toast } from "sonner";
import { Copy } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Courses } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/client";
import type { CourseListItem } from "@/lib/api/types";
import { useT } from "@/lib/i18n/provider";
import { qk } from "@/lib/query/keys";

/**
 * "Make my own copy" clone CTA (S4.11 · ADR-0028, FR-CLONE-25).
 *
 * Render gating (server still enforces ownership/quota/moderation —
 * this only hides a door the viewer can't use):
 *   - only for an `is_publicly_listed` source (`visibility === "public"`).
 *   - signed-in active user (`canClone`) → the clone button.
 *   - anonymous → a sign-in link with a `next` return path back to the
 *     course (same open-redirect-safe `/login?next=` pattern as enroll).
 *
 * The clone flag (`CLONE_ENABLED`) is **not** mirrored client-side: when
 * off, the POST 404s and we surface the generic error toast — exactly the
 * share/unshare flag pattern (`studio/[id]/page.tsx`). On 201 success the
 * server has already created the private draft + auto-enrolled the cloner,
 * so we invalidate `myCourses` + `enrollments` and route to the new draft.
 */
export function CloneButton({
  course,
  canClone,
  listed,
  className,
  variant = "outline",
}: {
  course: CourseListItem;
  /** Client mirror of `can_clone` (active signed-in user) — `useCapabilities().canClone`. */
  canClone: boolean;
  /**
   * Authoritative publicly-listed predicate when the caller has it (the detail
   * page's `is_publicly_listed`, which folds in moderation state). Falls back
   * to the `visibility === "public"` proxy that the catalog card relies on.
   */
  listed?: boolean;
  className?: string;
  variant?: "default" | "outline" | "secondary" | "ghost";
}) {
  const t = useT();
  const router = useRouter();
  const qc = useQueryClient();

  const clone = useMutation({
    mutationFn: () => Courses.clone({ key: course.id }),
    onSuccess: (created) => {
      toast.success(t("clone.success"));
      qc.invalidateQueries({ queryKey: qk.myCourses });
      qc.invalidateQueries({ queryKey: qk.enrollments });
      router.push(`/studio/draft/${created.id}`);
    },
    onError: (e: unknown) => toast.error(messageForError(e, t)),
  });

  // The CTA is meaningless for a course that isn't publicly listed — the
  // backend would 404 the clone (existence-hide). Hide it entirely.
  const isListed = listed ?? course.visibility === "public";
  if (!isListed) return null;

  if (!canClone) {
    const next = encodeURIComponent(`/courses/${course.slug}`);
    return (
      <Link href={`/login?next=${next}`} className={className}>
        <Button variant={variant} className="w-full" asChild>
          <span>
            <Copy className="h-4 w-4" aria-hidden />
            {t("clone.signInToClone")}
          </span>
        </Button>
      </Link>
    );
  }

  return (
    <Button
      variant={variant}
      className={className ?? "w-full"}
      onClick={() => clone.mutate()}
      disabled={clone.isPending}
    >
      <Copy className="h-4 w-4" aria-hidden />
      {clone.isPending ? t("clone.inProgress") : t("clone.cta")}
    </Button>
  );
}

/**
 * Map a clone failure to a localized toast. Keys off HTTP status first
 * (the quota ceilings — 429/409/413 per ADR-0028 §error table), with the
 * server `code` as a tiebreaker, falling back to the generic copy (covers
 * the flag-off 404, network errors, and anything unmapped).
 */
function messageForError(e: unknown, t: ReturnType<typeof useT>): string {
  if (e instanceof ApiError) {
    if (e.status === 429 || e.code === "clone.rate_limited") {
      return t("clone.error.rateLimited");
    }
    if (e.status === 409 || e.code === "clone.course_limit") {
      return t("clone.error.courseLimit");
    }
    if (e.status === 413 || e.code === "clone.source_too_large") {
      return t("clone.error.tooLarge");
    }
  }
  return t("clone.error.generic");
}
