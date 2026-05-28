"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { ApiError } from "@/lib/api/client";
import {
  Catalog,
  Courses,
  Ingest,
  type IngestPayload,
  type IngestSource,
} from "@/lib/api/endpoints";
import { useT } from "@/lib/i18n/provider";
import { qk } from "@/lib/query/keys";
import { useReturnFocus } from "@/lib/a11y/use-return-focus";
import { cn } from "@/lib/utils";

/**
 * Phase E3 — Import-from-URL studio modal.
 *
 * Flow:
 *   1. Instructor pastes a URL → ``Ingest.detect`` (cheap, regex-only)
 *      flips the badge that says "Detected: YouTube".
 *   2. Preview button → ``Ingest.preview`` returns a draft
 *      :class:`IngestPayload`. The tree of modules / lessons is
 *      rendered inline and the title fields are editable (one
 *      ``contentEditable`` per row, on-blur commit).
 *   3. Create-draft button → creates a *new* draft course (using the
 *      first subject by alphabetical order — same default as
 *      ``/studio/new``) and immediately runs ``Ingest.commit`` to
 *      append the modules + lessons.
 *
 * Loop 12 migrated this from a hand-rolled `fixed inset-0` dialog to
 * the shared `<Dialog>` primitive — Radix gives us a real focus trap,
 * aria-labelledby, Escape, click-outside, and focus restore.
 */

interface IngestModalProps {
  open: boolean;
  onClose: () => void;
}

const SOURCE_LABEL_KEY: Record<IngestSource, "studio.import.source.youtube" | "studio.import.source.notion" | "studio.import.source.google_docs" | "studio.import.source.unknown"> = {
  youtube: "studio.import.source.youtube",
  notion: "studio.import.source.notion",
  google_docs: "studio.import.source.google_docs",
  unknown: "studio.import.source.unknown",
};

export function IngestModal({ open, onClose }: IngestModalProps) {
  const t = useT();
  const router = useRouter();
  const subjectsQ = useQuery({
    queryKey: qk.subjects,
    queryFn: () => Catalog.subjects(),
    enabled: open,
  });

  const [url, setUrl] = useState("");
  const [source, setSource] = useState<IngestSource>("unknown");
  const [previewing, setPreviewing] = useState(false);
  const [committing, setCommitting] = useState(false);
  const [payload, setPayload] = useState<IngestPayload | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);

  // Controlled dialog with no <DialogTrigger> — Radix can't restore
  // focus to the opener on close, so capture it ourselves (WCAG 2.4.3).
  const onCloseAutoFocus = useReturnFocus(open);

  // Reset when the modal closes so re-opening starts fresh.
  useEffect(() => {
    if (!open) {
      setUrl("");
      setSource("unknown");
      setPayload(null);
      setPreviewError(null);
      setPreviewing(false);
      setCommitting(false);
    }
  }, [open]);

  // Pure regex source detection — runs locally on input so the badge
  // updates without hitting the API.
  useEffect(() => {
    const trimmed = url.trim();
    if (!trimmed) {
      setSource("unknown");
      return;
    }
    setSource(detectSourceLocal(trimmed));
  }, [url]);

  const totalLessons = useMemo(() => {
    if (!payload) return 0;
    return payload.modules.reduce((acc, m) => acc + m.lessons.length, 0);
  }, [payload]);

  const handlePreview = useCallback(async () => {
    setPreviewError(null);
    setPayload(null);
    setPreviewing(true);
    try {
      const result = await Ingest.preview(url.trim());
      setPayload(result);
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.message || t("studio.import.previewError")
          : t("studio.import.previewError");
      setPreviewError(msg);
    } finally {
      setPreviewing(false);
    }
  }, [t, url]);

  const handleCommit = useCallback(async () => {
    if (!payload) return;
    const subjects = subjectsQ.data ?? [];
    if (subjects.length === 0) {
      toast.error(t("studio.import.commitError"));
      return;
    }
    setCommitting(true);
    try {
      // Create a fresh draft course, then append the ingested
      // modules. v1 keeps these as two requests so the commit
      // endpoint can stay course-agnostic (and reusable for a future
      // "append to existing course" flow).
      const course = await Courses.create({
        title: payload.title.slice(0, 200),
        subject_id: subjects[0].id,
        overview: `Imported from ${payload.source_url}`,
      });
      const result = await Ingest.commit({
        course_id: course.id,
        payload,
      });
      toast.success(
        t("studio.import.success", {
          modules: result.modules,
          lessons: result.lessons,
        }),
      );
      onClose();
      router.push(`/studio/${course.id}`);
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.message || t("studio.import.commitError")
          : t("studio.import.commitError");
      toast.error(msg);
    } finally {
      setCommitting(false);
    }
  }, [onClose, payload, router, subjectsQ.data, t]);

  const sourceLabel = t(SOURCE_LABEL_KEY[source]);
  const canPreview = url.trim().length > 0 && source !== "unknown" && !previewing;

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent
        className="flex max-h-[90vh] w-full max-w-3xl flex-col gap-6 overflow-y-auto p-6 sm:p-8"
        srLabelClose={t("studio.import.cancel")}
        onCloseAutoFocus={onCloseAutoFocus}
      >
        <DialogHeader>
          <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
            {t("studio.cartouche")}
          </p>
          <DialogTitle className="font-display text-2xl leading-tight tracking-tight">
            {t("studio.import.title")}
          </DialogTitle>
          <DialogDescription>
            {t("studio.import.subtitle")}
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          <label className="font-body text-sm font-medium" htmlFor="ingest-url">
            {t("studio.import.urlLabel")}
          </label>
          <div className="flex flex-col gap-2 sm:flex-row">
            <Input
              id="ingest-url"
              type="url"
              inputMode="url"
              spellCheck={false}
              placeholder={t("studio.import.urlPlaceholder")}
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              className="flex-1"
            />
            <Button
              type="button"
              onClick={handlePreview}
              disabled={!canPreview}
              className="shrink-0"
            >
              {previewing ? (
                <>
                  <Loader2 className="me-2 h-4 w-4 animate-spin" />
                  {t("studio.import.previewing")}
                </>
              ) : (
                t("studio.import.preview")
              )}
            </Button>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={source === "unknown" ? "muted" : "secondary"}>
              {t("studio.import.detected", { source: sourceLabel })}
            </Badge>
          </div>
        </div>

        <div className="border-t border-border" />

        <div className="flex flex-col gap-3">
          {previewError ? (
            <p className="font-body text-sm text-destructive">{previewError}</p>
          ) : !payload ? (
            <p className="font-body text-sm text-muted-foreground">
              {t("studio.import.previewEmpty")}
            </p>
          ) : (
            <PreviewTree payload={payload} onPatch={setPayload} t={t} />
          )}
        </div>

        {payload ? (
          <footer className="flex flex-col items-stretch gap-2 border-t border-border pt-4 sm:flex-row sm:items-center sm:justify-between">
            <p className="font-mono text-xs tabular-nums text-muted-foreground">
              {t("studio.import.modulesCount", {
                n: payload.modules.length,
                l: totalLessons,
              })}
            </p>
            <div className="flex gap-2 sm:justify-end">
              <Button type="button" variant="ghost" onClick={onClose}>
                {t("studio.import.cancel")}
              </Button>
              <Button
                type="button"
                onClick={handleCommit}
                disabled={committing || totalLessons === 0}
              >
                {committing ? (
                  <>
                    <Loader2 className="me-2 h-4 w-4 animate-spin" />
                    {t("studio.import.committing")}
                  </>
                ) : (
                  t("studio.import.commit")
                )}
              </Button>
            </div>
          </footer>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

interface PreviewTreeProps {
  payload: IngestPayload;
  onPatch: (next: IngestPayload) => void;
  t: ReturnType<typeof useT>;
}

function PreviewTree({ payload, onPatch, t }: PreviewTreeProps) {
  return (
    <div className="flex flex-col gap-4">
      <label className="flex flex-col gap-1">
        <span className="sr-only">{t("studio.import.editTitleAria")}</span>
        <Input
          aria-label={t("studio.import.editTitleAria")}
          value={payload.title}
          onChange={(e) => onPatch({ ...payload, title: e.target.value })}
          className="font-display text-lg"
        />
      </label>
      <ul className="flex flex-col gap-3">
        {payload.modules.map((m, mi) => (
          <li
            key={mi}
            className={cn(
              "rounded-md border border-border p-3",
              "flex flex-col gap-2",
            )}
          >
            <Input
              aria-label={t("studio.import.editModuleAria")}
              value={m.title}
              onChange={(e) => {
                const next = { ...payload };
                next.modules = [...payload.modules];
                next.modules[mi] = { ...m, title: e.target.value };
                onPatch(next);
              }}
              className="font-display text-sm"
            />
            <ul className="ms-3 flex flex-col gap-2 border-s border-border ps-3">
              {m.lessons.map((l, li) => (
                <li key={li} className="flex flex-col gap-1">
                  <Input
                    aria-label={t("studio.import.editLessonAria")}
                    value={l.title}
                    onChange={(e) => {
                      const next = { ...payload };
                      next.modules = [...payload.modules];
                      const nm = { ...m, lessons: [...m.lessons] };
                      nm.lessons[li] = { ...l, title: e.target.value };
                      next.modules[mi] = nm;
                      onPatch(next);
                    }}
                    className="font-body text-sm"
                  />
                  {l.body ? (
                    <p className="line-clamp-2 font-body text-xs text-muted-foreground">
                      {t("studio.import.lessonExcerpt", {
                        text: l.body.slice(0, 240),
                      })}
                    </p>
                  ) : null}
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---------- Pure client-side source detection ----------

function detectSourceLocal(url: string): IngestSource {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return "unknown";
  }
  const host = parsed.hostname.toLowerCase();
  if (
    host === "youtube.com" ||
    host === "www.youtube.com" ||
    host === "m.youtube.com" ||
    host === "music.youtube.com" ||
    host === "youtu.be"
  ) {
    return "youtube";
  }
  if (
    host === "notion.so" ||
    host === "www.notion.so" ||
    host === "notion.site" ||
    host.endsWith(".notion.site")
  ) {
    return "notion";
  }
  if (host === "docs.google.com" && parsed.pathname.includes("/document/")) {
    return "google_docs";
  }
  return "unknown";
}

export { detectSourceLocal };
