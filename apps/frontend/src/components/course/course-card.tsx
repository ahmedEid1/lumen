import Link from "next/link";
import { Star, Users, Layers, GraduationCap } from "lucide-react";
import type { CourseListItem } from "@/lib/api/types";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";

export function CourseCard({ course }: { course: CourseListItem }) {
  return (
    <Link
      href={`/courses/${course.slug}`}
      className="surface group relative block h-full overflow-hidden rounded-lg transition-all duration-500 hover:-translate-y-1 hover:border-primary/40 hover:shadow-[0_18px_40px_-18px_hsl(var(--primary)/0.35)] focus-visible:border-primary/60 focus-visible:shadow-[0_0_0_2px_hsl(var(--primary)/0.4)]"
    >
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
          <div className="flex h-full items-center justify-center bg-[radial-gradient(ellipse_at_center,hsl(var(--primary)/0.10),transparent_65%)]">
            <GraduationCap
              className="h-16 w-16 text-primary/40 transition-transform duration-700 group-hover:scale-110 group-hover:text-primary/60"
              aria-hidden
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
            <Badge className="border border-primary/40 bg-primary/10 text-primary uppercase tracking-wider">
              Featured
            </Badge>
          )}
        </div>

        <h3 className="line-clamp-2 font-display text-xl font-medium leading-tight tracking-tight transition-colors group-hover:text-primary">
          {course.title}
        </h3>
        <p className="line-clamp-2 font-body text-sm leading-relaxed text-muted-foreground">
          {course.overview}
        </p>

        <div className="mt-auto flex items-center gap-3 pt-2">
          <Avatar className="h-7 w-7 border border-border/60">
            <AvatarImage src={course.owner.avatar_url ?? undefined} alt={course.owner.full_name} />
            <AvatarFallback>
              {course.owner.full_name.slice(0, 1).toUpperCase()}
            </AvatarFallback>
          </Avatar>
          <span className="font-body text-sm text-muted-foreground">{course.owner.full_name}</span>
        </div>

        <div className="flex items-center justify-between border-t border-border/60 pt-3 text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1.5 font-body">
            <Layers className="h-3.5 w-3.5 text-muted-foreground" />
            {course.modules_count} modules
          </span>
          <span className="inline-flex items-center gap-1.5">
            <Users className="h-3.5 w-3.5 text-muted-foreground" />
            {course.enrollments_count}
          </span>
          {course.avg_rating != null && (
            <span className="inline-flex items-center gap-1.5">
              <Star className="h-3.5 w-3.5 fill-primary text-primary" />
              {course.avg_rating.toFixed(1)}
            </span>
          )}
        </div>
      </div>
    </Link>
  );
}
