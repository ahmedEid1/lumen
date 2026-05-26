"use client";

import Link from "next/link";
import { Star, Users, Layers, GraduationCap } from "lucide-react";
import type { CourseListItem } from "@/lib/api/types";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { useT } from "@/lib/i18n/provider";

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
  return (
    <Link
      href={`/courses/${course.slug}`}
      className="surface group flex h-full flex-col overflow-hidden transition-colors duration-[160ms] hover:border-foreground/30"
    >
      {/* Cover */}
      <div className="relative aspect-[16/10] w-full overflow-hidden border-b border-border bg-muted">
        {course.cover_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={course.cover_url}
            alt=""
            className="h-full w-full object-cover"
          />
        ) : (
          <div className="flex h-full items-center justify-center">
            <GraduationCap className="h-12 w-12 text-muted-foreground/40" aria-hidden />
          </div>
        )}
      </div>

      <div className="flex flex-1 flex-col gap-3 p-5">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant="outline">{course.subject.title}</Badge>
          <Badge variant="muted">{course.difficulty}</Badge>
          {course.is_featured && <Badge>{t("catalog.featuredBadge")}</Badge>}
        </div>

        <h3 className="line-clamp-2 font-display text-base leading-tight tracking-tight text-foreground transition-colors duration-[160ms] group-hover:text-muted-foreground">
          {course.title}
        </h3>
        <p className="line-clamp-2 font-body text-sm leading-relaxed text-muted-foreground">
          {course.overview}
        </p>

        <div className="mt-auto flex items-center gap-3 pt-2">
          <Avatar className="h-6 w-6 border border-border">
            <AvatarImage src={course.owner.avatar_url ?? undefined} alt={course.owner.full_name} />
            <AvatarFallback>
              {course.owner.full_name.slice(0, 1).toUpperCase()}
            </AvatarFallback>
          </Avatar>
          <span className="font-body text-xs text-muted-foreground">{course.owner.full_name}</span>
        </div>

        <div className="flex items-center justify-between border-t border-border pt-3 font-mono text-xs tabular-nums text-muted-foreground">
          <span className="inline-flex items-center gap-1.5">
            <Layers className="h-3.5 w-3.5" />
            {t("courseCard.modulesCount", { n: course.modules_count })}
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
  );
}
