"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { Admin } from "@/lib/api/endpoints";
import {
  ALL_REASON_CODES,
  QUARANTINE_REASONS,
  type ModerationQueueItem,
  type ReasonCode,
  type ReportOut,
  type ReportResolveAction,
} from "@/lib/api/types";
import { qk } from "@/lib/query/keys";
import { useAuth } from "@/lib/auth/store";
import { useT } from "@/lib/i18n/provider";
import type { MessageKey } from "@/lib/i18n/messages/en";
import { useReturnFocus } from "@/lib/a11y/use-return-focus";

/**
 * Admin moderation (S6.11 / FR-MOD-15).
 *
 * Two tabs: the pending review QUEUE and the open REPORTS list. The queue
 * gets the full admin-authority action set (approve / reject / delist /
 * relist / remove); remove and report-resolve open confirmation dialogs with
 * a reason picker drawn from the shared taxonomy. All user-supplied text is
 * rendered as inert text (FR-MOD-13): titles and the already-sanitized report
 * note are plain string children, never `dangerouslySetInnerHTML`.
 */
export default function AdminModerationPage() {
  const { user, ready } = useAuth();
  const router = useRouter();
  const t = useT();

  useEffect(() => {
    if (!ready) return;
    if (!user) router.replace("/login?next=/admin/moderation");
    else if (user.role !== "admin") router.replace("/dashboard");
  }, [ready, user, router]);

  if (!ready || !user || user.role !== "admin") return null;

  return (
    <div className="container mx-auto px-6 py-14">
      <header className="mb-10 flex flex-col gap-3">
        <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          {t("adminModeration.cartouche")}
        </p>
        <h1 className="font-display text-3xl leading-tight tracking-tight sm:text-4xl">
          {t("adminModeration.title")}
        </h1>
        <p className="font-body text-sm text-muted-foreground">
          {t("adminModeration.subtitle")}
        </p>
      </header>

      <Tabs defaultValue="queue">
        <TabsList>
          <TabsTrigger value="queue">{t("adminModeration.tab.queue")}</TabsTrigger>
          <TabsTrigger value="reports">{t("adminModeration.tab.reports")}</TabsTrigger>
        </TabsList>
        <TabsContent value="queue">
          <QueueTab />
        </TabsContent>
        <TabsContent value="reports">
          <ReportsTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}

// ---------------- Queue tab ----------------

type QueueAction = "approve" | "reject" | "delist" | "relist";

function QueueTab() {
  const t = useT();
  const qc = useQueryClient();
  const [removeTarget, setRemoveTarget] = useState<ModerationQueueItem | null>(null);

  const queueQ = useQuery({
    queryKey: qk.moderationQueue,
    queryFn: () => Admin.moderationQueue(),
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: qk.moderationQueue });
    qc.invalidateQueries({ queryKey: qk.catalogRoot });
  };

  const act = useMutation({
    mutationFn: ({ id, action }: { id: string; action: QueueAction }) => {
      const fn = {
        approve: Admin.approveCourse,
        reject: Admin.rejectCourse,
        delist: Admin.delistCourse,
        relist: Admin.relistCourse,
      }[action];
      return fn(id, {});
    },
    onSuccess: (_d, vars) => {
      toast.success(t(`adminModeration.${vars.action}Toast` as MessageKey));
      invalidate();
    },
    onError: (e: Error) => toast.error(e?.message ?? t("adminModeration.actionError")),
  });

  const rows: ModerationQueueItem[] = queueQ.data ?? [];

  return (
    <>
      {queueQ.isLoading ? (
        <p className="font-body text-sm text-muted-foreground">{t("common.loading")}</p>
      ) : rows.length === 0 ? (
        <p
          className="font-body text-sm text-muted-foreground"
          data-testid="moderation-empty"
        >
          {t("adminModeration.empty")}
        </p>
      ) : (
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-border text-start font-mono text-xs uppercase tracking-wider text-muted-foreground">
              <th className="py-2 text-start">{t("adminModeration.col.course")}</th>
              <th className="py-2 text-start">{t("adminModeration.col.owner")}</th>
              <th className="py-2 text-start">{t("adminModeration.col.submitted")}</th>
              <th className="py-2 text-end">{t("adminModeration.col.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.id} className="border-b border-border" data-testid="moderation-row">
                <td className="py-3">
                  {/* Inert text — never render user content as markup (FR-MOD-13). */}
                  <Link href={`/courses/${c.slug}`} className="font-body hover:underline">
                    {c.title}
                  </Link>
                  <div className="mt-1 flex gap-2">
                    <Badge variant="outline">{c.visibility}</Badge>
                    {c.moderation_state ? (
                      <Badge variant="outline">{c.moderation_state}</Badge>
                    ) : null}
                    {/* F3: honest queue-reason badge — a flagged-but-still-listed
                        course (report accumulation) vs one awaiting first review. */}
                    <Badge
                      variant={c.queue_reason === "flagged" ? "destructive" : "secondary"}
                      data-testid="queue-reason-badge"
                    >
                      {t(`adminModeration.reason.${c.queue_reason}` as MessageKey)}
                    </Badge>
                  </div>
                </td>
                <td className="py-3 font-body text-muted-foreground">{c.owner.full_name}</td>
                <td className="py-3 font-mono text-xs tabular-nums text-muted-foreground">
                  {new Date(c.created_at).toLocaleDateString()}
                </td>
                <td className="py-3">
                  <div className="flex flex-wrap justify-end gap-2">
                    <Button
                      size="sm"
                      onClick={() => act.mutate({ id: c.id, action: "approve" })}
                      disabled={act.isPending}
                    >
                      {t("adminModeration.approve")}
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => act.mutate({ id: c.id, action: "reject" })}
                      disabled={act.isPending}
                    >
                      {t("adminModeration.reject")}
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => act.mutate({ id: c.id, action: "delist" })}
                      disabled={act.isPending}
                    >
                      {t("adminModeration.delist")}
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => act.mutate({ id: c.id, action: "relist" })}
                      disabled={act.isPending}
                    >
                      {t("adminModeration.relist")}
                    </Button>
                    <Button
                      size="sm"
                      variant="destructive"
                      onClick={() => setRemoveTarget(c)}
                      disabled={act.isPending}
                    >
                      {t("adminModeration.remove")}
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <RemoveDialog
        course={removeTarget}
        onClose={() => setRemoveTarget(null)}
        onRemoved={invalidate}
      />
    </>
  );
}

// ---------------- Remove confirmation dialog (reason required) ----------------

function RemoveDialog({
  course,
  onClose,
  onRemoved,
}: {
  course: ModerationQueueItem | null;
  onClose: () => void;
  onRemoved: () => void;
}) {
  const t = useT();
  const [reason, setReason] = useState<ReasonCode | "">("");
  const [note, setNote] = useState("");
  const open = course !== null;
  const onCloseAutoFocus = useReturnFocus(open);

  // Reset the form whenever the dialog is (re)opened for a course.
  useEffect(() => {
    if (open) {
      setReason("");
      setNote("");
    }
  }, [open, course?.id]);

  const remove = useMutation({
    mutationFn: () =>
      Admin.removeCourse(course!.id, {
        reason: reason as ReasonCode,
        note: note || null,
      }),
    onSuccess: () => {
      toast.success(t("adminModeration.removeToast"));
      onRemoved();
      onClose();
    },
    onError: (e: Error) => toast.error(e?.message ?? t("adminModeration.actionError")),
  });

  const willQuarantine = reason !== "" && QUARANTINE_REASONS.includes(reason);

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md" onCloseAutoFocus={onCloseAutoFocus}>
        <DialogHeader>
          <DialogTitle className="text-destructive">
            {t("adminModeration.confirmRemoveTitle")}
          </DialogTitle>
          <DialogDescription>{t("adminModeration.confirmRemoveBody")}</DialogDescription>
        </DialogHeader>

        <ReasonField reason={reason} setReason={setReason} note={note} setNote={setNote} />

        {willQuarantine ? (
          <p
            className="font-body text-sm text-destructive"
            role="alert"
            data-testid="quarantine-warning"
          >
            {t("adminModeration.quarantineWarning")}
          </p>
        ) : null}

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            variant="destructive"
            data-testid="confirm-remove"
            disabled={reason === "" || remove.isPending}
            onClick={() => remove.mutate()}
          >
            {t("adminModeration.remove")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------- Shared reason + note field ----------------

function ReasonField({
  reason,
  setReason,
  note,
  setNote,
}: {
  reason: ReasonCode | "";
  setReason: (r: ReasonCode) => void;
  note: string;
  setNote: (n: string) => void;
}) {
  const t = useT();
  return (
    <div className="space-y-4">
      <div className="space-y-1.5">
        <label className="font-body text-sm font-medium">
          {t("adminModeration.reasonLabel")}
        </label>
        <Select value={reason} onValueChange={(v) => setReason(v as ReasonCode)}>
          <SelectTrigger aria-label={t("adminModeration.reasonLabel")}>
            <SelectValue placeholder={t("adminModeration.reasonPlaceholder")} />
          </SelectTrigger>
          <SelectContent>
            {ALL_REASON_CODES.map((code) => (
              <SelectItem key={code} value={code}>
                {t(`reason.${code}` as MessageKey)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="space-y-1.5">
        <label htmlFor="mod-note" className="font-body text-sm font-medium">
          {t("adminModeration.noteLabel")}
        </label>
        <Textarea
          id="mod-note"
          rows={3}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder={t("adminModeration.notePlaceholder")}
        />
      </div>
    </div>
  );
}

// ---------------- Reports tab ----------------

function ReportsTab() {
  const t = useT();
  const qc = useQueryClient();
  const [resolveTarget, setResolveTarget] = useState<ReportOut | null>(null);

  const reportsQ = useQuery({
    queryKey: qk.reports,
    queryFn: () => Admin.reports({ status: "open" }),
  });

  const rows: ReportOut[] = reportsQ.data ?? [];

  return (
    <>
      {reportsQ.isLoading ? (
        <p className="font-body text-sm text-muted-foreground">{t("common.loading")}</p>
      ) : rows.length === 0 ? (
        <p
          className="font-body text-sm text-muted-foreground"
          data-testid="reports-empty"
        >
          {t("adminModeration.reports.empty")}
        </p>
      ) : (
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-border text-start font-mono text-xs uppercase tracking-wider text-muted-foreground">
              <th className="py-2 text-start">{t("adminModeration.reports.col.reason")}</th>
              <th className="py-2 text-start">{t("adminModeration.reports.col.reporter")}</th>
              <th className="py-2 text-start">{t("adminModeration.reports.col.note")}</th>
              <th className="py-2 text-start">{t("adminModeration.reports.col.status")}</th>
              <th className="py-2 text-end">{t("adminModeration.reports.col.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-b border-border" data-testid="report-row">
                <td className="py-3">
                  <Badge variant="outline">{r.reason}</Badge>
                </td>
                <td className="py-3 font-mono text-xs text-muted-foreground">
                  {r.reporter_id}
                </td>
                {/* Inert: the note is already sanitized server-side (FR-MOD-13). */}
                <td className="py-3 font-body text-muted-foreground">{r.note ?? "—"}</td>
                <td className="py-3 font-mono text-xs text-muted-foreground">{r.status}</td>
                <td className="py-3 text-end">
                  <Button size="sm" variant="outline" onClick={() => setResolveTarget(r)}>
                    {t("adminModeration.reports.resolve")}
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <ResolveDialog
        report={resolveTarget}
        onClose={() => setResolveTarget(null)}
        onResolved={() => {
          qc.invalidateQueries({ queryKey: qk.reports });
          qc.invalidateQueries({ queryKey: qk.moderationQueue });
          qc.invalidateQueries({ queryKey: qk.catalogRoot });
        }}
      />
    </>
  );
}

function ResolveDialog({
  report,
  onClose,
  onResolved,
}: {
  report: ReportOut | null;
  onClose: () => void;
  onResolved: () => void;
}) {
  const t = useT();
  const [action, setAction] = useState<ReportResolveAction>("dismiss");
  const [reason, setReason] = useState<ReasonCode | "">("");
  const [note, setNote] = useState("");
  const open = report !== null;
  const onCloseAutoFocus = useReturnFocus(open);

  useEffect(() => {
    if (open) {
      setAction("dismiss");
      setReason("");
      setNote("");
    }
  }, [open, report?.id]);

  const resolve = useMutation({
    mutationFn: () =>
      Admin.resolveReport(report!.id, {
        action,
        reason: reason === "" ? null : (reason as ReasonCode),
        note: note || null,
      }),
    onSuccess: () => {
      toast.success(t("adminModeration.reports.resolveToast"));
      onResolved();
      onClose();
    },
    onError: (e: Error) =>
      toast.error(e?.message ?? t("adminModeration.reports.resolveError")),
  });

  // remove requires a reason; dismiss/delist do not.
  const needsReason = action === "remove";
  const confirmDisabled = (needsReason && reason === "") || resolve.isPending;

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md" onCloseAutoFocus={onCloseAutoFocus}>
        <DialogHeader>
          <DialogTitle>{t("adminModeration.reports.resolveTitle")}</DialogTitle>
          <DialogDescription>
            {t("adminModeration.reports.resolveBody")}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-1.5">
          <label className="font-body text-sm font-medium">
            {t("adminModeration.reports.actionLabel")}
          </label>
          <Select
            value={action}
            onValueChange={(v) => setAction(v as ReportResolveAction)}
          >
            <SelectTrigger aria-label={t("adminModeration.reports.actionLabel")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="dismiss">
                {t("adminModeration.reports.action.dismiss")}
              </SelectItem>
              <SelectItem value="delist">
                {t("adminModeration.reports.action.delist")}
              </SelectItem>
              <SelectItem value="remove">
                {t("adminModeration.reports.action.remove")}
              </SelectItem>
            </SelectContent>
          </Select>
        </div>

        {action !== "dismiss" ? (
          <ReasonField reason={reason} setReason={setReason} note={note} setNote={setNote} />
        ) : null}

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            variant={action === "remove" ? "destructive" : "default"}
            data-testid="confirm-resolve"
            disabled={confirmDisabled}
            onClick={() => resolve.mutate()}
          >
            {t("adminModeration.reports.resolve")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
