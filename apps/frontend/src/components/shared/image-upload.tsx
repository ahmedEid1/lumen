"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Upload, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";

type PresignResponse = {
  method: "PUT";
  url: string;
  key: string;
  headers: Record<string, string>;
  expires_in: number;
  public_url: string;
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
  const [busy, setBusy] = useState(false);
  const effectiveAccept = accept ?? DEFAULT_ACCEPT[kind];
  const limit = maxBytes ?? DEFAULT_MAX[kind];

  async function handleFile(file: File) {
    if (file.size > limit) {
      toast.error(`File is too large (max ${Math.round(limit / (1024 * 1024))} MB)`);
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
      const put = await fetch(presign.url, {
        method: presign.method,
        headers: presign.headers,
        body: file,
      });
      if (!put.ok) throw new Error(`Upload failed (${put.status})`);
      onChange(presign.public_url);
      toast.success("Uploaded");
    } catch (e: any) {
      toast.error(e?.message ?? "Upload failed");
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
      {label && <p className="text-sm font-medium">{label}</p>}
      <div className="flex items-center gap-3">
        {value ? (
          <img src={value} alt="" className={`${previewClass} border bg-muted`} />
        ) : (
          <div
            className={`${previewClass} flex items-center justify-center border bg-muted text-xs text-muted-foreground`}
          >
            none
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
            <span className="inline-flex h-10 cursor-pointer items-center justify-center gap-2 rounded-md border bg-background px-4 text-sm hover:bg-muted disabled:opacity-50">
              <Upload className="h-4 w-4" /> {busy ? "Uploading…" : "Choose file"}
            </span>
          </label>
          {value && (
            <Button variant="ghost" size="sm" onClick={() => onChange(null)} disabled={busy}>
              <X className="mr-1 h-4 w-4" /> Remove
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
