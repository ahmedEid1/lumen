"use client";

import Link from "next/link";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { OriginAttribution } from "@/components/course/origin-attribution";
import type { CourseDetail } from "@/lib/api/types";
import { useT } from "@/lib/i18n/provider";

/**
 * Course detail page header — badges + title + overview + instructor
 * row. Extracted from the 444-LoC course-detail-view monolith in
 * Loop 16 per AUDIT.md §3 ("Three sibling sections … live in one
 * big inline JSX blob").
 */
export function CourseHeader({ course }: { course: CourseDetail }) {
  const t = useT();
  // S6.10 read-time anonymization (DR-19): the API serializes a tombstoned
  // owner's `full_name` as the i18n KEY "common.deletedUser"; resolve it at the
  // render site (mirrors origin-attribution.tsx, Gate-B B2) so t()'s flat
  // var-replace doesn't paint the raw key.
  const ownerIsDeleted = course.owner.full_name === "common.deletedUser";
  const ownerName = ownerIsDeleted ? t("common.deletedUser") : course.owner.full_name;
  return (
    <header className="space-y-4">
      <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
        {t("courseDetail.cartouche")}
      </p>

      <div className="flex flex-wrap gap-1.5">
        <Link
          href={`/courses?subject=${encodeURIComponent(course.subject.slug)}`}
          aria-label={t("courseDetail.moreFromSubject", { name: course.subject.title })}
        >
          <Badge variant="secondary" className="cursor-pointer hover:bg-muted">
            {course.subject.title}
          </Badge>
        </Link>
        <Link
          href={`/courses?difficulty=${encodeURIComponent(course.difficulty)}`}
          aria-label={t("courseDetail.moreFromDifficulty", { name: course.difficulty })}
        >
          <Badge variant="muted" className="cursor-pointer hover:bg-muted/80">
            {course.difficulty}
          </Badge>
        </Link>
        {course.tags.map((tag) => (
          <Link
            key={tag.id}
            href={`/courses?tag=${encodeURIComponent(tag.slug)}`}
            aria-label={t("courseDetail.moreFromTag", { name: tag.name })}
          >
            <Badge variant="outline" className="cursor-pointer hover:bg-muted">
              {tag.name}
            </Badge>
          </Link>
        ))}
      </div>

      <h1 className="break-words font-display text-4xl leading-tight tracking-tight md:text-5xl">
        {course.title}
      </h1>
      <p className="max-w-2xl break-words font-body text-base leading-relaxed text-muted-foreground">
        {course.overview}
      </p>

      <div className="flex items-center gap-3 pt-1">
        <Avatar className="border border-border">
          <AvatarImage
            src={course.owner.avatar_url ?? undefined}
            alt={ownerName}
          />
          <AvatarFallback>
            {ownerName.slice(0, 1).toUpperCase()}
          </AvatarFallback>
        </Avatar>
        <div className="font-body text-sm">
          <div className="font-medium text-foreground">{ownerName}</div>
          <div className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
            {t("courseDetail.instructor")}
          </div>
        </div>
      </div>

      {/* Structured, read-only clone provenance (ADR-0028 / FR-CLONE-10).
          Kept separate from the editable title/overview above so attribution
          can't be spoofed. Renders nothing for a from-scratch course. */}
      <OriginAttribution origin={course.origin} className="pt-1" />
    </header>
  );
}
