"use client";

import { use } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, ShieldX } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Cartouche } from "@/components/lumen/cartouche";
import { Glyph } from "@/components/lumen/glyph";
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
    <div className="container mx-auto flex max-w-xl flex-col items-center px-4 py-20">
      <Cartouche className="mb-5">{t("verifyCert.cartouche")}</Cartouche>
      <Card className="w-full scroll-paper border-gold/20">
        <CardContent className="space-y-5 pt-8">
          <header className="flex flex-col items-center gap-2 text-center">
            <h1 className="font-display text-2xl font-medium tracking-tight">
              {t("verifyCert.title")}
            </h1>
            <p className="font-body text-sm text-muted-foreground">
              {t("verifyCert.subtitle")}
            </p>
          </header>

          {q.isLoading && (
            <p className="text-center font-body text-muted-foreground">
              {t("verifyCert.checking")}
            </p>
          )}

          {q.error && (
            <div className="space-y-3 text-center">
              <ShieldX className="mx-auto h-10 w-10 text-destructive" aria-hidden />
              <p className="font-body">
                {q.error instanceof ApiError && q.error.status === 404
                  ? t("verifyCert.notFound")
                  : (q.error as Error).message}
              </p>
              <code className="block rounded-md border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
                {id}
              </code>
              <Link href="/">
                <Button variant="outline">{t("verifyCert.goHome")}</Button>
              </Link>
            </div>
          )}

          {q.data && (
            <div className="space-y-5 text-center">
              <Glyph
                name="aten"
                size={80}
                mode="art"
                className="mx-auto drop-shadow-[0_0_24px_hsl(var(--gold-leaf)/0.5)]"
              />
              <div className="space-y-1">
                <p className="text-[0.65rem] uppercase tracking-[0.32em] text-gold/70">
                  {t("verifyCert.issuedTo")}
                </p>
                <p className="font-display text-2xl font-medium">{q.data.learner_name}</p>
              </div>
              <div className="space-y-1">
                <p className="text-[0.65rem] uppercase tracking-[0.32em] text-gold/70">
                  {t("verifyCert.forCompleting")}
                </p>
                <Link
                  href={`/courses/${q.data.course_slug}`}
                  className="font-display text-lg italic text-gold underline-offset-4 hover:underline"
                >
                  {q.data.course_title}
                </Link>
              </div>
              <p className="inline-flex items-center gap-2 font-body text-sm text-muted-foreground">
                <CheckCircle2 className="h-4 w-4 text-gold" />
                {t("verifyCert.issuedOn", {
                  date: new Date(q.data.issued_at).toLocaleDateString(),
                })}
              </p>
              <code className="block break-all rounded-md border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
                {q.data.certificate_id}
              </code>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
