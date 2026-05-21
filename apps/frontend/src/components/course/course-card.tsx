import Link from "next/link";
import { Star, Users, Layers } from "lucide-react";
import type { CourseListItem } from "@/lib/api/types";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";

export function CourseCard({ course }: { course: CourseListItem }) {
  return (
    <Link href={`/courses/${course.slug}`} className="group block">
      <Card className="h-full transition-shadow group-hover:shadow-md">
        <div className="aspect-video w-full overflow-hidden rounded-t-xl bg-gradient-to-br from-primary/15 to-accent/15">
          {course.cover_url ? (
            <img
              src={course.cover_url}
              alt=""
              className="h-full w-full object-cover transition-transform group-hover:scale-[1.02]"
            />
          ) : (
            <div className="flex h-full items-center justify-center text-4xl font-bold text-primary/40">
              {course.title.slice(0, 1).toUpperCase()}
            </div>
          )}
        </div>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="secondary">{course.subject.title}</Badge>
            <Badge variant="muted">{course.difficulty}</Badge>
            {course.is_featured && <Badge>Featured</Badge>}
          </div>
          <CardTitle className="line-clamp-2">{course.title}</CardTitle>
          <CardDescription className="line-clamp-2">{course.overview}</CardDescription>
        </CardHeader>
        <CardContent className="flex items-center gap-3">
          <Avatar className="h-7 w-7">
            <AvatarImage src={course.owner.avatar_url ?? undefined} alt={course.owner.full_name} />
            <AvatarFallback>{course.owner.full_name.slice(0, 1).toUpperCase()}</AvatarFallback>
          </Avatar>
          <span className="text-sm text-muted-foreground">{course.owner.full_name}</span>
        </CardContent>
        <CardFooter className="justify-between text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1">
            <Layers className="h-3.5 w-3.5" />
            {course.modules_count} modules
          </span>
          <span className="inline-flex items-center gap-1">
            <Users className="h-3.5 w-3.5" />
            {course.enrollments_count}
          </span>
          {course.avg_rating != null && (
            <span className="inline-flex items-center gap-1">
              <Star className="h-3.5 w-3.5 fill-current" />
              {course.avg_rating.toFixed(1)}
            </span>
          )}
        </CardFooter>
      </Card>
    </Link>
  );
}
