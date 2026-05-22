"use client";

import { use } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Award, CheckCircle2, ShieldX } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api, ApiError } from "@/lib/api/client";
import { useT } from "@/lib/i18n/provider";

type VerifyOut = {
  certificate_id: string;
  course_id: string;
  course_title: string;
  course_slug: string;
  learner_name: string;
  issued_at: string;
};

/**
 * Certificate verification — Workbench repaint.
 *
 * Single centered card, mono eyebrow, no gold/lapis chrome. The
 * certificate ID is rendered in JBM mono inside a muted code block,
 * because it is the load-bearing artifact on this surface.
 */
export default function VerifyCertificatePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const t = useT();
  const q = useQuery({
    queryKey: ["verify", id],
    queryFn: () => api<VerifyOut>(`/api/v1/certificates/verify/${encodeURIComponent(id)}`),
    retry: false,
  });

  return (
    <div className="mx-auto flex w-full max-w-[520px] flex-col px-6 py-20">
      <div className="rounded-md border border-border bg-card p-8">
        <p className="mb-6 font-mono text-xs uppercase tracking-wider text-muted-foreground">
          {t("verifyCert.cartouche")}
        </p>
        <header className="mb-7 space-y-2">
          <h1 className="font-display text-3xl leading-tight tracking-tight">
            {t("verifyCert.title")}
          </h1>
          <p className="font-body text-sm text-muted-foreground">
            {t("verifyCert.subtitle")}
          </p>
        </header>

        <div aria-live="polite">
          {q.isLoading && (
            <p className="font-body text-sm text-muted-foreground">
              {t("verifyCert.checking")}
            </p>
          )}

          {q.error && (
            <div className="space-y-4">
              <div className="flex items-start gap-3">
                <ShieldX
                  className="mt-0.5 h-5 w-5 flex-none text-destructive"
                  aria-hidden
                />
                <p className="font-body text-sm text-destructive">
                  {q.error instanceof ApiError && q.error.status === 404
                    ? t("verifyCert.notFound")
                    : (q.error as Error).message}
                </p>
              </div>
              <code className="block break-all rounded-md border border-border bg-muted px-3 py-2 font-mono text-xs text-muted-foreground">
                {id}
              </code>
              <Link href="/">
                <Button variant="outline" className="w-full">
                  {t("verifyCert.goHome")}
                </Button>
              </Link>
            </div>
          )}

          {q.data && (
            <div className="space-y-5">
              <div className="flex items-center gap-3 border-b border-border pb-5">
                <Award className="h-5 w-5 flex-none text-primary" aria-hidden />
                <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
                  {t("verifyCert.issuedTo")}
                </p>
              </div>
              <p className="font-display text-2xl leading-tight tracking-tight">
                {q.data.learner_name}
              </p>
              <div className="space-y-1">
                <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
                  {t("verifyCert.forCompleting")}
                </p>
                <Link
                  href={`/courses/${q.data.course_slug}`}
                  className="font-display text-lg leading-tight text-foreground underline-offset-4 hover:underline"
                >
                  {q.data.course_title}
                </Link>
              </div>
              <p className="inline-flex items-center gap-2 font-body text-sm text-muted-foreground">
                <CheckCircle2 className="h-4 w-4 text-primary" aria-hidden />
                {t("verifyCert.issuedOn", {
                  date: new Date(q.data.issued_at).toLocaleDateString(),
                })}
              </p>
              <code className="block break-all rounded-md border border-border bg-muted px-3 py-2 font-mono text-xs text-muted-foreground">
                {q.data.certificate_id}
              </code>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
