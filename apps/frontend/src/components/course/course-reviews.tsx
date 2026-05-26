"use client";

import { Star } from "lucide-react";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { MyReviewEditor } from "@/components/course/my-review-editor";
import type { CourseDetail, ReviewOut } from "@/lib/api/types";
import { useT } from "@/lib/i18n/provider";
import { cn } from "@/lib/utils";

type User = {
  id: string;
};

/**
 * Course reviews list + own-review editor. Extracted from
 * course-detail-view monolith in Loop 16.
 */
export function CourseReviews({
  course,
  reviews,
  user,
}: {
  course: CourseDetail;
  reviews: ReviewOut[] | undefined;
  user: User | null;
}) {
  const t = useT();
  return (
    <Card>
      <CardHeader>
        <CardTitle className="font-display text-xl leading-tight">
          {t("course.reviews")}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {user && course.is_enrolled && user.id !== course.owner.id && (
          <MyReviewEditor
            courseId={course.id}
            myReview={reviews?.find((r) => r.author.id === user.id) ?? null}
          />
        )}
        {reviews && reviews.length > 0 ? (
          <ul className="divide-y divide-border">
            {reviews.map((r) => (
              <li key={r.id} className="py-3 first:pt-0 last:pb-0">
                <div className="flex items-center gap-2 text-sm">
                  <Avatar className="h-6 w-6 border border-border">
                    <AvatarImage
                      src={r.author.avatar_url ?? undefined}
                      alt={r.author.full_name}
                    />
                    <AvatarFallback>{r.author.full_name.slice(0, 1)}</AvatarFallback>
                  </Avatar>
                  <span className="font-body font-medium text-foreground">
                    {r.author.full_name}
                  </span>
                  <span className="ms-auto inline-flex items-center gap-0.5">
                    {Array.from({ length: 5 }).map((_, i) => (
                      <Star
                        key={i}
                        className={cn(
                          "h-3.5 w-3.5",
                          i < r.rating
                            ? "fill-primary text-primary"
                            : "fill-none text-muted-foreground/40",
                        )}
                      />
                    ))}
                  </span>
                </div>
                {r.body && (
                  <p className="mt-2 font-body text-sm text-muted-foreground">{r.body}</p>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="font-body text-sm text-muted-foreground">
            {t("courseDetail.beFirst")}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
