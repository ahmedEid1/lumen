"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Cartouche } from "@/components/lumen/cartouche";
import { Glyph } from "@/components/lumen/glyph";
import { api } from "@/lib/api/client";
import { useT } from "@/lib/i18n/provider";

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<ResetFallback />}>
      <ResetForm />
    </Suspense>
  );
}

function ResetFallback() {
  return (
    <div className="container mx-auto flex max-w-md flex-col px-4 py-20">
      <div className="h-64 animate-pulse rounded-md border border-border bg-card/40" aria-hidden />
    </div>
  );
}

function ResetForm() {
  const router = useRouter();
  const params = useSearchParams();
  const t = useT();
  const token = params.get("token") ?? "";
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!token) {
      toast.error(t("auth.reset.tokenError"));
      return;
    }
    setSubmitting(true);
    try {
      await api("/api/v1/auth/password-reset/confirm", {
        method: "POST",
        body: { token, password },
      });
      toast.success(t("auth.reset.successToast"));
      router.push("/login");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t("auth.reset.error"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="container mx-auto flex max-w-md flex-col items-center px-4 py-20">
      <Cartouche className="mb-5">{t("auth.reset.cartouche")}</Cartouche>
      <Card className="w-full scroll-paper border-gold/20">
        <CardContent className="space-y-6 pt-8">
          <header className="flex flex-col items-center gap-3 text-center">
            <Glyph
              name="djed"
              size={42}
              mode="tint"
              className="text-gold/85 drop-shadow-[0_0_10px_hsl(var(--gold-leaf)/0.4)]"
            />
            <h1 className="font-display text-3xl font-medium tracking-tight">
              {t("auth.reset.heading")}
            </h1>
            <p className="font-body text-sm text-muted-foreground">{t("auth.reset.subtitle")}</p>
          </header>

          {!token ? (
            <p className="font-body text-sm text-muted-foreground">
              {t("auth.reset.missingToken")}{" "}
              <Link
                href="/forgot-password"
                className="text-gold underline-offset-4 hover:underline"
              >
                {t("auth.reset.requestNew")}
              </Link>
              .
            </p>
          ) : (
            <form className="space-y-4" onSubmit={onSubmit}>
              <Input
                type="password"
                placeholder={t("auth.reset.passwordPlaceholder")}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                minLength={12}
                autoComplete="new-password"
                required
                className="border-gold/25 bg-background/60 focus-visible:border-gold/60"
              />
              <Button type="submit" className="w-full" disabled={submitting}>
                {submitting ? t("auth.reset.submitting") : t("auth.reset.submit")}
              </Button>
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
