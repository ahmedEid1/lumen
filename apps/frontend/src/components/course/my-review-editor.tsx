"use client";

import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Star, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Reviews } from "@/lib/api/endpoints";
import type { ReviewOut } from "@/lib/api/types";
import { qk } from "@/lib/query/keys";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";

type Props = {
  courseId: string;
  myReview: ReviewOut | null;
};

export function MyReviewEditor({ courseId, myReview }: Props) {
  const qc = useQueryClient();
  const t = useT();
  const [rating, setRating] = useState(myReview?.rating ?? 0);
  const [hovered, setHovered] = useState(0);
  const [body, setBody] = useState(myReview?.body ?? "");

  useEffect(() => {
    setRating(myReview?.rating ?? 0);
    setBody(myReview?.body ?? "");
  }, [myReview?.id, myReview?.rating, myReview?.body]);

  const save = useMutation({
    mutationFn: () => Reviews.upsert(courseId, { rating, body }),
    onSuccess: () => {
      toast.success(myReview ? t("review.updatedToast") : t("review.postedToast"));
      qc.invalidateQueries({ queryKey: qk.reviews(courseId) });
      qc.invalidateQueries({ queryKey: qk.course(courseId) });
    },
    onError: (e: Error) => toast.error(e?.message ?? t("review.saveError")),
  });

  const remove = useMutation({
    mutationFn: () => Reviews.remove(courseId),
    onSuccess: () => {
      toast.success(t("review.removedToast"));
      setRating(0);
      setBody("");
      qc.invalidateQueries({ queryKey: qk.reviews(courseId) });
      qc.invalidateQueries({ queryKey: qk.course(courseId) });
    },
    onError: (e: Error) => toast.error(e?.message ?? t("review.removeError")),
  });

  const display = hovered || rating;

  return (
    <div className="surface rounded-md p-4">
      <p className="mb-2 font-body text-xs font-medium uppercase tracking-[0.18em] text-primary">
        {myReview ? t("review.yours") : t("review.leave")}
      </p>
      <div
        className="mb-3 flex items-center gap-1"
        role="radiogroup"
        aria-label={t("review.ratingAria")}
      >
        {[1, 2, 3, 4, 5].map((n) => (
          <button
            key={n}
            type="button"
            role="radio"
            aria-checked={rating === n}
            aria-label={n === 1 ? t("review.starAria", { n }) : t("review.starsAria", { n })}
            onMouseEnter={() => setHovered(n)}
            onMouseLeave={() => setHovered(0)}
            onClick={() => setRating(n)}
            className="rounded p-0.5 transition-transform hover:scale-110"
          >
            <Star
              className={cn(
                "h-6 w-6 transition-colors",
                n <= display ? "fill-primary text-primary" : "text-muted-foreground/60",
              )}
            />
          </button>
        ))}
      </div>
      <Textarea
        rows={3}
        value={body}
        onChange={(e) => setBody(e.target.value)}
        placeholder={t("review.bodyPlaceholder")}
        maxLength={4000}
      />
      <div className="mt-3 flex items-center justify-between">
        <Button onClick={() => save.mutate()} disabled={!rating || save.isPending}>
          {save.isPending
            ? t("common.saving")
            : myReview
              ? t("review.update")
              : t("review.post")}
        </Button>
        {myReview && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => remove.mutate()}
            disabled={remove.isPending}
            className="text-muted-foreground hover:text-destructive"
          >
            <Trash2 className="me-1 h-4 w-4" /> {t("studioEdit.remove")}
          </Button>
        )}
      </div>
    </div>
  );
}
