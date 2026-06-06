"use client";

import { useId, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { Flag } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { Courses } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/client";
import { ALL_REASON_CODES, type ReasonCode } from "@/lib/api/types";
import type { CourseDetail } from "@/lib/api/types";
import { useT } from "@/lib/i18n/provider";
import { useReturnFocus } from "@/lib/a11y/use-return-focus";

type Viewer = { id: string } | null;

/**
 * "Report this course" affordance (W11 · FR-MOD-11 / S6.3).
 *
 * The user-side seam over `POST /courses/{id}/report`. Render gating mirrors
 * the backend's existence-hide rules so we only ever show a door the viewer can
 * actually walk through:
 *
 *   - anonymous viewers: hidden (reporting requires an authenticated user).
 *   - the course owner: hidden (the server rejects own-course reports with
 *     `report.own_course`; the owner has nothing to report).
 *   - everyone else who is signed in: a quiet ghost trigger that opens the
 *     dialog.
 *
 * The dialog collects a reason from the REAL backend taxonomy
 * (`ALL_REASON_CODES`, lockstep with `moderation_taxonomy.ReasonCode`) plus an
 * optional free-text note (`sanitize_note`d server-side). On a 201 success we
 * toast and flip the trigger to an inert "Reported" for the rest of the session
 * — no client-side dedupe beyond that, the server is the authority (it coalesces
 * a repeat report onto the reporter's open row).
 *
 * Errors are mapped off the server `code` first (the specific 422 own-course /
 * 403 ineligible / 429 rate-limited cases), then HTTP status, falling back to a
 * generic toast (covers the 404 existence-hide for a course that went un-listed
 * between page-load and submit, plus network errors).
 */
export function ReportButton({
  course,
  user,
  className,
}: {
  course: Pick<CourseDetail, "id" | "owner">;
  user: Viewer;
  className?: string;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState<ReasonCode | "">("");
  const [note, setNote] = useState("");
  // Inert for the rest of the session once the server has accepted a report.
  const [reported, setReported] = useState(false);
  const onCloseAutoFocus = useReturnFocus(open);
  const reasonLabelId = useId();
  const noteId = useId();

  const report = useMutation({
    mutationFn: (vars: { reason: ReasonCode; note: string | null }) =>
      Courses.report(course.id, vars),
    onSuccess: () => {
      toast.success(t("report.success"));
      setReported(true);
      setOpen(false);
      setReason("");
      setNote("");
    },
    onError: (e: unknown) => toast.error(messageForError(e, t)),
  });

  // Anonymous viewers never see the trigger; neither does the owner (the server
  // would reject their report with `report.own_course`).
  if (!user || user.id === course.owner.id) return null;

  if (reported) {
    return (
      <Button
        type="button"
        variant="ghost"
        size="sm"
        disabled
        className={className ?? "w-full text-muted-foreground"}
      >
        <Flag className="h-4 w-4" aria-hidden />
        {t("report.reported")}
      </Button>
    );
  }

  function submit() {
    if (!reason) return;
    report.mutate({ reason, note: note.trim() ? note.trim() : null });
  }

  return (
    <>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={() => setOpen(true)}
        className={className ?? "w-full text-muted-foreground"}
      >
        <Flag className="h-4 w-4" aria-hidden />
        {t("report.cta")}
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent
          srLabelClose={t("common.close")}
          onCloseAutoFocus={onCloseAutoFocus}
        >
          <DialogHeader>
            <DialogTitle>{t("report.dialogTitle")}</DialogTitle>
            <DialogDescription>{t("report.dialogBody")}</DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="space-y-1.5">
              <label
                id={reasonLabelId}
                className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground"
              >
                {t("report.reasonLabel")}
              </label>
              <Select
                value={reason}
                onValueChange={(v) => setReason(v as ReasonCode)}
              >
                <SelectTrigger aria-labelledby={reasonLabelId}>
                  <SelectValue placeholder={t("report.reasonPlaceholder")} />
                </SelectTrigger>
                <SelectContent>
                  {ALL_REASON_CODES.map((code) => (
                    <SelectItem key={code} value={code}>
                      {t(`reason.${code}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1.5">
              <label
                htmlFor={noteId}
                className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground"
              >
                {t("report.detailsLabel")}
              </label>
              <Textarea
                id={noteId}
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder={t("report.detailsPlaceholder")}
                rows={4}
                maxLength={5000}
              />
            </div>
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => setOpen(false)}
              disabled={report.isPending}
            >
              {t("common.cancel")}
            </Button>
            <Button
              type="button"
              onClick={submit}
              disabled={!reason || report.isPending}
            >
              {report.isPending ? t("report.submitting") : t("report.submit")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

/**
 * Map a report failure to a localized toast. Keys off the server `code` first
 * (the precise own-course / ineligible / rate-limited cases), then HTTP status
 * (slowapi's per-user 429 carries its own code), falling back to the generic
 * copy (the 404 existence-hide for a course that went un-listed, network errors,
 * anything unmapped).
 */
function messageForError(e: unknown, t: ReturnType<typeof useT>): string {
  if (e instanceof ApiError) {
    if (e.code === "report.own_course" || e.status === 422) {
      return t("report.ownCourse");
    }
    if (e.code === "report.ineligible" || e.status === 403) {
      return t("report.ineligible");
    }
    if (e.code === "course.report_rate_limited" || e.status === 429) {
      return t("report.rateLimited");
    }
  }
  return t("report.error");
}
