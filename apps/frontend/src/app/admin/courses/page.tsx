"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Search, Star, StarOff } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DataTable, type Column } from "@/components/ui/data-table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api/client";
import { Admin } from "@/lib/api/endpoints";
import {
  ALL_REASON_CODES,
  QUARANTINE_REASONS,
  type CourseListItem,
  type ReasonCode,
} from "@/lib/api/types";
import { qk } from "@/lib/query/keys";
import { useT } from "@/lib/i18n/provider";
import type { MessageKey } from "@/lib/i18n/messages/en";
import { useReturnFocus } from "@/lib/a11y/use-return-focus";

/**
 * Admin courses — Workbench repaint.
 *
 * Dense table on the page background, header in mono uppercase, rows
 * separated by hairline borders. Owner names + subjects in body text,
 * statuses + featured flag as bordered badges, no nested card chrome.
 *
 * See docs/superpowers/specs/2026-05-22-lumen-rebuild-design.md §2.
 */
export default function AdminCourses() {
  const qc = useQueryClient();
  const t = useT();
  const [q, setQ] = useState("");
  const [onlyFeatured, setOnlyFeatured] = useState(false);

  const KEY = ["admin", "courses", { q, onlyFeatured }] as const;
  const coursesQ = useQuery({
    queryKey: KEY,
    queryFn: () => {
      const qs = new URLSearchParams();
      if (q) qs.set("q", q);
      if (onlyFeatured) qs.set("only_featured", "true");
      return api<CourseListItem[]>(`/api/v1/admin/courses${qs.toString() ? `?${qs}` : ""}`);
    },
  });

  const [removeTarget, setRemoveTarget] = useState<CourseListItem | null>(null);

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["admin", "courses"] });
    qc.invalidateQueries({ queryKey: qk.catalogRoot });
  };

  const toggle = useMutation({
    mutationFn: ({ id, next }: { id: string; next: boolean }) =>
      api<CourseListItem>(`/api/v1/admin/courses/${id}/feature`, {
        method: "PATCH",
        body: { is_featured: next },
      }),
    onSuccess: () => {
      toast.success(t("adminCourses.successToast"));
      qc.invalidateQueries({ queryKey: ["admin", "courses"] });
    },
    onError: (e: Error) => toast.error(e?.message ?? t("adminCourses.error")),
  });

  // Moderation row actions (FR-MOD-15) — delist/relist are reversible; remove
  // is destructive and goes through a reason-gated confirmation dialog.
  const moderate = useMutation({
    mutationFn: ({ id, action }: { id: string; action: "delist" | "relist" }) =>
      action === "delist" ? Admin.delistCourse(id, {}) : Admin.relistCourse(id, {}),
    onSuccess: () => {
      toast.success(t("adminCourses.actionToast"));
      invalidate();
    },
    onError: (e: Error) => toast.error(e?.message ?? t("adminCourses.actionError")),
  });

  return (
    <div className="container mx-auto max-w-6xl px-6 py-14">
      <header className="mb-8 flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div className="flex flex-col gap-3">
          <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
            {t("adminCourses.cartouche")}
          </p>
          <h1 className="font-display text-3xl leading-tight tracking-tight sm:text-4xl">
            {t("adminCourses.title")}
          </h1>
          <p className="font-body text-sm text-muted-foreground">{t("adminCourses.subtitle")}</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative w-72">
            <Search className="absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={t("adminCourses.searchPlaceholder")}
              className="ps-9"
            />
          </div>
          <div className="inline-flex items-center gap-2 font-body text-sm">
            <Switch
              id="featured-only"
              checked={onlyFeatured}
              onCheckedChange={setOnlyFeatured}
            />
            <label htmlFor="featured-only">{t("adminCourses.featuredOnly")}</label>
          </div>
        </div>
      </header>

      <DataTable<CourseListItem>
        ariaLabel={t("adminCourses.title")}
        columns={[
          {
            id: "course",
            header: t("adminCourses.col.course"),
            cell: (c) => (
              <>
                <Link
                  href={`/courses/${c.slug}`}
                  className="font-body text-sm font-medium text-foreground transition-colors duration-base hover:text-muted-foreground"
                  target="_blank"
                >
                  {c.title}
                </Link>
                <div className="font-body text-xs text-muted-foreground">
                  {c.subject.title}
                </div>
              </>
            ),
          },
          {
            id: "owner",
            header: t("adminCourses.col.owner"),
            cell: (c) => (
              <span className="font-body text-sm text-muted-foreground">
                {c.owner.full_name}
              </span>
            ),
          },
          {
            id: "status",
            header: t("adminCourses.col.status"),
            cell: (c) => (
              <Badge
                variant={
                  c.status === "published"
                    ? "default"
                    : c.status === "archived"
                      ? "muted"
                      : "secondary"
                }
              >
                {t(`course.status.${c.status}` as MessageKey)}
              </Badge>
            ),
          },
          {
            id: "visibility",
            header: t("adminCourses.col.visibility"),
            cell: (c) => (
              <Badge variant="outline">
                {t(`adminCourses.visibility.${c.visibility}` as MessageKey)}
              </Badge>
            ),
          },
          {
            id: "moderation",
            header: t("adminCourses.col.moderation"),
            // The real moderation_state is admin-visible (FR-VIS-21); `null`
            // renders as "—".
            cell: (c) =>
              c.moderation_state ? (
                <Badge
                  variant={
                    c.moderation_state === "rejected" || c.moderation_state === "delisted"
                      ? "destructive"
                      : c.moderation_state === "approved"
                        ? "default"
                        : "muted"
                  }
                >
                  {t(`adminCourses.moderation.${c.moderation_state}` as MessageKey)}
                </Badge>
              ) : (
                <span className="font-mono text-xs text-muted-foreground">—</span>
              ),
          },
          {
            id: "featured",
            header: t("adminCourses.col.featured"),
            cell: (c) =>
              c.is_featured ? (
                <Badge>{t("catalog.featuredBadge")}</Badge>
              ) : (
                <span className="font-mono text-xs text-muted-foreground">—</span>
              ),
          },
          {
            id: "action",
            header: t("adminCourses.col.action"),
            headerClassName: "text-end",
            className: "text-end",
            cell: (c) => (
              <div className="flex flex-wrap justify-end gap-1.5">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => toggle.mutate({ id: c.id, next: !c.is_featured })}
                  disabled={toggle.isPending}
                >
                  {c.is_featured ? (
                    <>
                      <StarOff className="me-1 h-4 w-4" /> {t("adminCourses.unfeature")}
                    </>
                  ) : (
                    <>
                      <Star className="me-1 h-4 w-4" /> {t("adminCourses.feature")}
                    </>
                  )}
                </Button>
                {c.moderation_state === "delisted" ? (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => moderate.mutate({ id: c.id, action: "relist" })}
                    disabled={moderate.isPending}
                  >
                    {t("adminCourses.relist")}
                  </Button>
                ) : (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => moderate.mutate({ id: c.id, action: "delist" })}
                    disabled={moderate.isPending}
                  >
                    {t("adminCourses.delist")}
                  </Button>
                )}
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={() => setRemoveTarget(c)}
                >
                  {t("adminCourses.remove")}
                </Button>
              </div>
            ),
          },
        ] as Column<CourseListItem>[]}
        rows={coursesQ.data ?? []}
        rowKey={(c) => c.id}
        loading={coursesQ.isLoading}
        emptyState={
          <p className="font-body text-sm text-muted-foreground">
            {t("adminCourses.empty")}
          </p>
        }
      />

      <CourseRemoveDialog
        course={removeTarget}
        onClose={() => setRemoveTarget(null)}
        onRemoved={invalidate}
      />
    </div>
  );
}

// Reason-gated destructive remove confirmation (FR-MOD-15). Mirrors the
// /admin/moderation remove flow so the two surfaces stay consistent.
function CourseRemoveDialog({
  course,
  onClose,
  onRemoved,
}: {
  course: CourseListItem | null;
  onClose: () => void;
  onRemoved: () => void;
}) {
  const t = useT();
  const [reason, setReason] = useState<ReasonCode | "">("");
  const [note, setNote] = useState("");
  const open = course !== null;
  const onCloseAutoFocus = useReturnFocus(open);

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
      toast.success(t("adminCourses.actionToast"));
      onRemoved();
      onClose();
    },
    onError: (e: Error) => toast.error(e?.message ?? t("adminCourses.actionError")),
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
            <label htmlFor="course-remove-note" className="font-body text-sm font-medium">
              {t("adminModeration.noteLabel")}
            </label>
            <Textarea
              id="course-remove-note"
              rows={3}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder={t("adminModeration.notePlaceholder")}
            />
          </div>
        </div>

        {willQuarantine ? (
          <p className="font-body text-sm text-destructive" role="alert">
            {t("adminModeration.quarantineWarning")}
          </p>
        ) : null}

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            variant="destructive"
            disabled={reason === "" || remove.isPending}
            onClick={() => remove.mutate()}
          >
            {t("adminCourses.remove")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
