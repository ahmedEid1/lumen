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

type Props = {
  courseId: string;
  myReview: ReviewOut | null;
};

export function MyReviewEditor({ courseId, myReview }: Props) {
  const qc = useQueryClient();
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
      toast.success(myReview ? "Review updated" : "Review posted");
      qc.invalidateQueries({ queryKey: qk.reviews(courseId) });
      qc.invalidateQueries({ queryKey: qk.course(courseId) });
    },
    onError: (e: any) => toast.error(e?.message ?? "Could not save review"),
  });

  const remove = useMutation({
    mutationFn: () => Reviews.remove(courseId),
    onSuccess: () => {
      toast.success("Review removed");
      setRating(0);
      setBody("");
      qc.invalidateQueries({ queryKey: qk.reviews(courseId) });
      qc.invalidateQueries({ queryKey: qk.course(courseId) });
    },
    onError: (e: any) => toast.error(e?.message ?? "Could not remove review"),
  });

  const display = hovered || rating;

  return (
    <div className="rounded-lg border bg-muted/30 p-4">
      <p className="mb-2 text-sm font-medium">{myReview ? "Your review" : "Leave a review"}</p>
      <div className="mb-3 flex items-center gap-1" role="radiogroup" aria-label="Rating">
        {[1, 2, 3, 4, 5].map((n) => (
          <button
            key={n}
            type="button"
            role="radio"
            aria-checked={rating === n}
            aria-label={`${n} star${n === 1 ? "" : "s"}`}
            onMouseEnter={() => setHovered(n)}
            onMouseLeave={() => setHovered(0)}
            onClick={() => setRating(n)}
            className="rounded p-0.5 hover:scale-110"
          >
            <Star
              className={cn(
                "h-6 w-6 transition-colors",
                n <= display ? "fill-amber-500 text-amber-500" : "text-muted-foreground",
              )}
            />
          </button>
        ))}
      </div>
      <Textarea
        rows={3}
        value={body}
        onChange={(e) => setBody(e.target.value)}
        placeholder="Optional thoughts…"
        maxLength={4000}
      />
      <div className="mt-3 flex items-center justify-between">
        <Button onClick={() => save.mutate()} disabled={!rating || save.isPending}>
          {save.isPending ? "Saving…" : myReview ? "Update review" : "Post review"}
        </Button>
        {myReview && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => remove.mutate()}
            disabled={remove.isPending}
          >
            <Trash2 className="me-1 h-4 w-4" /> Remove
          </Button>
        )}
      </div>
    </div>
  );
}
