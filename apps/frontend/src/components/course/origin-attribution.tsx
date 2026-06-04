"use client";

import Link from "next/link";
import { GitFork } from "lucide-react";
import type { CourseOrigin } from "@/lib/api/types";
import { useT } from "@/lib/i18n/provider";

/**
 * Structured "Based on …" clone attribution (S4.11 · ADR-0028,
 * FR-CLONE-10/23, DR-19).
 *
 * Renders the immutable, **server-written** provenance — deliberately NOT
 * editable-looking (no inputs, plain text + an optional link), so a cloner
 * cannot spoof attribution by editing their copy's title/overview.
 *
 *   - `origin_available` (origin still live + publicly listed, computed
 *     read-time in S4.8) → "Based on {title} by {author}" + a "View
 *     original" link to the source.
 *   - otherwise → plain "Based on a course that is no longer available"
 *     text with NO link (FR-DEL-01). The deleted-owner case is already
 *     folded in upstream: `origin_owner_name` carries the localized
 *     "a deleted user" label (DR-19) when the owner is tombstoned.
 *
 * Only the immediate parent is shown — `root_origin_course_id` is never
 * rendered (D-35/D-40). Returns `null` for a from-scratch course.
 */
export function OriginAttribution({
  origin,
  className,
}: {
  origin: CourseOrigin | null;
  className?: string;
}) {
  const t = useT();
  if (!origin) return null;

  const base = "flex flex-col gap-1 text-sm text-muted-foreground";
  const cls = className ? `${base} ${className}` : base;

  if (!origin.origin_available || !origin.origin_course_id) {
    return (
      <div className={cls} data-testid="origin-attribution">
        <span className="inline-flex items-center gap-1.5">
          <GitFork className="h-3.5 w-3.5 shrink-0" aria-hidden />
          {t("clone.basedOnUnavailable")}
        </span>
      </div>
    );
  }

  return (
    <div className={cls} data-testid="origin-attribution">
      <span className="inline-flex items-center gap-1.5">
        <GitFork className="h-3.5 w-3.5 shrink-0" aria-hidden />
        {t("clone.basedOn", {
          title: origin.origin_title ?? "",
          author: origin.origin_owner_name ?? "",
        })}
      </span>
      <Link
        href={`/courses/${origin.origin_course_id}`}
        className="text-foreground font-medium underline-offset-4 hover:underline"
      >
        {t("clone.viewSource")}
      </Link>
    </div>
  );
}
