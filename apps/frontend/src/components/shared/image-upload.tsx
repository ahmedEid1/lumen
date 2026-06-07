"use client";

/* eslint-disable @next/next/no-img-element */
import { useState } from "react";
import { toast } from "sonner";
import { Upload, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";
import { useT } from "@/lib/i18n/provider";
import { cn } from "@/lib/utils";

type PresignResponse = {
  method: "POST";
  url: string;
  fields: Record<string, string>;
  key: string;
  expires_in: number;
  public_url: string;
  max_bytes: number;
};

type Props = {
  kind: "avatar" | "cover" | "lesson" | "attachment";
  value: string | null;
  onChange: (publicUrl: string | null) => void;
  accept?: string;
  maxBytes?: number;
  /** Render the preview as a circle (avatar) or rounded rectangle (cover). */
  shape?: "circle" | "rect";
  label?: string;
};

const DEFAULT_ACCEPT: Record<Props["kind"], string> = {
  avatar: "image/png,image/jpeg,image/webp",
  cover: "image/png,image/jpeg,image/webp",
  lesson: "image/*,video/mp4,video/webm,application/pdf",
  attachment: "*/*",
};

const DEFAULT_MAX: Record<Props["kind"], number> = {
  avatar: 5 * 1024 * 1024,
  cover: 10 * 1024 * 1024,
  lesson: 1024 * 1024 * 1024,
  attachment: 100 * 1024 * 1024,
};

export function ImageUpload({
  kind,
  value,
  onChange,
  accept,
  maxBytes,
  shape = "circle",
  label,
}: Props) {
  const t = useT();
  const [busy, setBusy] = useState(false);
  const effectiveAccept = accept ?? DEFAULT_ACCEPT[kind];
  const limit = maxBytes ?? DEFAULT_MAX[kind];

  async function handleFile(file: File) {
    if (file.size > limit) {
      toast.error(t("upload.tooLarge", { n: Math.round(limit / (1024 * 1024)) }));
      return;
    }
    setBusy(true);
    try {
      const presign = await api<PresignResponse>("/api/v1/uploads/sign", {
        method: "POST",
        body: {
          filename: file.name,
          content_type: file.type || "application/octet-stream",
          kind,
          size_bytes: file.size,
        },
      });
      // S3 multipart POST: all server-signed fields, then the file
      // last (S3 expects the bytes under the "file" field name).
      const formData = new FormData();
      Object.entries(presign.fields).forEach(([k, v]) => formData.append(k, v));
      formData.append("file", file);
      const upload = await fetch(presign.url, {
        method: "POST",
        body: formData,
      });
      if (!upload.ok) {
        // S3 enforces content-length-range as a 403 EntityTooLarge —
        // surface a friendly message instead of the raw status.
        if (upload.status === 403) {
          throw new Error(
            t("upload.exceedsLimit", {
              n: Math.round(presign.max_bytes / (1024 * 1024)),
              kind,
            }),
          );
        }
        throw new Error(t("upload.failedWithStatus", { status: upload.status }));
      }
      onChange(presign.public_url);
      toast.success(t("upload.successToast"));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t("upload.failed"));
    } finally {
      setBusy(false);
    }
  }

  const previewClass =
    shape === "circle"
      ? "h-20 w-20 rounded-full object-cover"
      : "aspect-video w-full max-w-sm rounded-md object-cover";

  return (
    <div className="space-y-2">
      {label && <p className="font-body text-sm font-medium">{label}</p>}
      <div className="flex items-center gap-3">
        {value ? (
          <img
            src={value}
            alt=""
            className={`${previewClass} border border-border/60 bg-muted`}
          />
        ) : (
          <div
            className={`${previewClass} flex items-center justify-center border border-border/60 bg-muted/40 font-body text-xs italic text-muted-foreground`}
          >
            {t("upload.none")}
          </div>
        )}
        <div className="flex flex-col gap-2">
          <label className="inline-flex">
            <input
              type="file"
              accept={effectiveAccept}
              className="sr-only"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void handleFile(f);
                e.target.value = "";
              }}
              disabled={busy}
            />
            {/* The <span> can never match :disabled (it's not a form
                control), so the old disabled:opacity-50 was dead CSS — while
                uploading, the picker kept full pointer + hover affordance
                with the input disabled underneath (a false affordance).
                Gate the appearance on `busy` instead. */}
            <span
              className={cn(
                "inline-flex h-10 items-center justify-center gap-2 rounded-md border border-border/60 bg-background px-4 font-body text-sm transition-colors",
                busy
                  ? "cursor-not-allowed opacity-50"
                  : "cursor-pointer hover:border-primary/60 hover:bg-primary/5",
              )}
            >
              <Upload className="h-4 w-4 text-muted-foreground" />{" "}
              {busy ? t("upload.uploading") : t("upload.choose")}
            </span>
          </label>
          {value && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onChange(null)}
              disabled={busy}
              className="text-muted-foreground hover:text-destructive"
            >
              <X className="me-1 h-4 w-4" /> {t("studioEdit.remove")}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
