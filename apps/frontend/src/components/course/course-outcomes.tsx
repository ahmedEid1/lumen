"use client";

import { Check } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { CourseDetail } from "@/lib/api/types";
import { useT } from "@/lib/i18n/provider";

/**
 * "What you'll learn" outcomes card. Renders nothing if the course
 * has no outcomes set. Extracted from course-detail-view monolith
 * in Loop 16.
 */
export function CourseOutcomes({ course }: { course: CourseDetail }) {
  const t = useT();
  if (!course.learning_outcomes || course.learning_outcomes.length === 0) {
    return null;
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle className="font-display text-xl leading-tight">
          {t("course.whatYoullLearn")}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ul className="grid gap-2 sm:grid-cols-2">
          {course.learning_outcomes.map((outcome, idx) => (
            <li key={idx} className="flex items-start gap-2 font-body text-sm">
              <Check className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
              <span className="min-w-0 break-words">{outcome}</span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
