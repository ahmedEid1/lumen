"use client";

import Link from "next/link";
import { useState } from "react";
import { Star, Users, Layers, GraduationCap } from "lucide-react";
import type { CourseListItem } from "@/lib/api/types";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { CloneButton } from "@/components/course/clone-button";
import { useCapabilities } from "@/lib/auth/capabilities";
import { useT, useTN } from "@/lib/i18n/provider";

/**
 * Workbench course card.
 *
 * Flat `surface` block, border-elevation only. Hover shifts the border
 * colour and nudges the title to lime — no lift, no glow, no cover
 * scale. The cover sits flush against the metadata band; meta row uses
 * mono+tabular-nums so module / student / rating counts stay aligned.
 */
export function CourseCard({ course }: { course: CourseListItem }) {
  const t = useT();
  const tn = useTN();
  const { canClone } = useCapabilities();
  // The clone CTA sits in a sibling footer *outside* the card Link — a
  // button/link nested inside an <a> is invalid HTML and breaks keyboard
  // a11y. The CloneButton hides itself unless the course is publicly listed
  // (visibility === "public"); anonymous viewers get a sign-in affordance.
  const showCloneFooter = course.visibility === "public";
  // QA-loop iter 1: cover_url often points at picsum.photos which
  // flakes with ERR_CONNECTION_CLOSED on a portion of cold visits.
  // Track per-render whether the image failed and swap to the same
  // GraduationCap empty state used when cover_url is null — keeps the
  // catalog grid heights stable and stops the broken-image glyph from
  // painting in the meantime.
  const [coverFailed, setCoverFailed] = useState(false);
  const showCover = !!course.cover_url && !coverFailed;
  return (
    <div className="surface group hover:border-foreground/30 flex h-full flex-col overflow-hidden transition-colors duration-[160ms]">
      <Link href={`/courses/${course.slug}`} className="flex flex-1 flex-col">
        {/* Cover */}
        <div className="border-border bg-muted relative aspect-[16/10] w-full overflow-hidden border-b">
          {showCover ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={course.cover_url ?? ""}
              alt=""
              className="h-full w-full object-cover"
              onError={() => setCoverFailed(true)}
            />
          ) : (
            <div className="flex h-full items-center justify-center">
              <GraduationCap className="text-muted-foreground/40 h-12 w-12" aria-hidden />
            </div>
          )}
        </div>

        <div className="flex flex-1 flex-col gap-3 p-5">
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge variant="outline">{course.subject.title}</Badge>
            <Badge variant="muted">{course.difficulty}</Badge>
            {course.is_featured && <Badge>{t("catalog.featuredBadge")}</Badge>}
          </div>

          <h3 className="font-display text-foreground group-hover:text-muted-foreground line-clamp-2 text-base leading-tight tracking-tight transition-colors duration-[160ms]">
            {course.title}
          </h3>
          <p className="font-body text-muted-foreground line-clamp-2 text-sm leading-relaxed">
            {course.overview}
          </p>

          <div className="mt-auto flex items-center gap-3 pt-2">
            <Avatar className="border-border h-6 w-6 border">
              <AvatarImage
                src={course.owner.avatar_url ?? undefined}
                alt={course.owner.full_name}
              />
              <AvatarFallback>{course.owner.full_name.slice(0, 1).toUpperCase()}</AvatarFallback>
            </Avatar>
            <span className="font-body text-muted-foreground text-xs">
              {course.owner.full_name}
            </span>
          </div>

          <div className="border-border text-muted-foreground flex items-center justify-between border-t pt-3 font-mono text-xs tabular-nums">
            <span className="inline-flex items-center gap-1.5">
              <Layers className="h-3.5 w-3.5" />
              {tn("courseCard.modulesCount", course.modules_count)}
            </span>
            <span className="inline-flex items-center gap-1.5">
              <Users className="h-3.5 w-3.5" />
              {course.enrollments_count}
            </span>
            {course.avg_rating != null && (
              <span className="inline-flex items-center gap-1.5">
                <Star className="h-3.5 w-3.5" />
                {course.avg_rating.toFixed(1)}
              </span>
            )}
          </div>
        </div>
      </Link>

      {/* Clone CTA — outside the card Link to keep interactive elements
          un-nested. Hidden unless the course is publicly listed. */}
      {showCloneFooter && (
        <div className="border-border border-t p-3">
          <CloneButton course={course} canClone={canClone} variant="ghost" />
        </div>
      )}
    </div>
  );
}
