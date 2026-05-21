import Link from "next/link";
import { Star, Users, Layers } from "lucide-react";
import type { CourseListItem } from "@/lib/api/types";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Glyph } from "@/components/lumen/glyph";

/**
 * Course card styled as a papyrus scroll: thin gold-edge border,
 * vellum tint, hieroglyph monogram when no cover art is supplied,
 * subtle rise + glow on hover.
 */
export function CourseCard({ course }: { course: CourseListItem }) {
  return (
    <Link
      href={`/courses/${course.slug}`}
      className="group relative block h-full overflow-hidden rounded-md border border-border bg-card transition-all duration-500 hover:-translate-y-1 hover:border-gold/45 hover:shadow-[0_18px_40px_-18px_hsl(var(--gold-leaf)/0.45)] focus-visible:border-gold/60 focus-visible:shadow-[0_0_0_2px_hsl(var(--gold-leaf)/0.4)] scroll-paper"
    >
      {/* Pinnacle — gold capping line */}
      <span
        aria-hidden
        className="absolute inset-x-8 top-0 h-px bg-gradient-to-r from-transparent via-gold/55 to-transparent opacity-60 transition-opacity group-hover:opacity-100"
      />

      {/* Cover */}
      <div className="relative aspect-[16/10] w-full overflow-hidden bg-muted/40">
        {course.cover_url ? (
          <>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={course.cover_url}
              alt=""
              className="h-full w-full object-cover transition-transform duration-700 group-hover:scale-[1.04]"
            />
            <span
              aria-hidden
              className="absolute inset-0 bg-gradient-to-t from-card via-card/30 to-transparent"
            />
          </>
        ) : (
          <div className="flex h-full items-center justify-center bg-[radial-gradient(ellipse_at_center,hsl(var(--gold-leaf)/0.12),transparent_65%)]">
            <Glyph
              name="ankh"
              size={72}
              mode="tint"
              className="text-gold/35 transition-transform duration-700 group-hover:scale-110 group-hover:text-gold/60"
            />
          </div>
        )}
      </div>

      <div className="flex flex-1 flex-col gap-3 p-5">
        <div className="flex flex-wrap items-center gap-1.5 text-[0.65rem]">
          <Badge variant="secondary" className="font-body uppercase tracking-wider">
            {course.subject.title}
          </Badge>
          <Badge variant="muted" className="font-body uppercase tracking-wider">
            {course.difficulty}
          </Badge>
          {course.is_featured && (
            <Badge className="border border-gold/40 bg-gold/10 text-gold uppercase tracking-wider">
              Featured
            </Badge>
          )}
        </div>

        <h3 className="line-clamp-2 font-display text-xl font-medium leading-tight tracking-tight transition-colors group-hover:text-gold">
          {course.title}
        </h3>
        <p className="line-clamp-2 font-body text-sm leading-relaxed text-muted-foreground">
          {course.overview}
        </p>

        <div className="mt-auto flex items-center gap-3 pt-2">
          <Avatar className="h-7 w-7 border border-gold/30">
            <AvatarImage src={course.owner.avatar_url ?? undefined} alt={course.owner.full_name} />
            <AvatarFallback>
              {course.owner.full_name.slice(0, 1).toUpperCase()}
            </AvatarFallback>
          </Avatar>
          <span className="font-body text-sm text-muted-foreground">{course.owner.full_name}</span>
        </div>

        <div className="flex items-center justify-between border-t border-border/60 pt-3 text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1.5 font-body">
            <Layers className="h-3.5 w-3.5 text-gold/70" />
            {course.modules_count} modules
          </span>
          <span className="inline-flex items-center gap-1.5">
            <Users className="h-3.5 w-3.5 text-gold/70" />
            {course.enrollments_count}
          </span>
          {course.avg_rating != null && (
            <span className="inline-flex items-center gap-1.5">
              <Star className="h-3.5 w-3.5 fill-gold text-gold" />
              {course.avg_rating.toFixed(1)}
            </span>
          )}
        </div>
      </div>
    </Link>
  );
}
