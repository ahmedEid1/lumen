"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api/client";
import { useT } from "@/lib/i18n/provider";

/**
 * Reset password — Workbench repaint.
 *
 * Token comes from the email link as `?token=…`. We keep the
 * single-card pattern and route errors / missing-token states inline
 * rather than into a separate surface.
 */
export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<ResetFallback />}>
      <ResetForm />
    </Suspense>
  );
}

function ResetFallback() {
  return (
    <div className="mx-auto flex w-full max-w-[440px] flex-col px-6 py-24">
      <div className="skeleton h-64 w-full" aria-hidden />
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
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!token) {
      setError(t("auth.reset.tokenError"));
      toast.error(t("auth.reset.tokenError"));
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await api("/api/v1/auth/password-reset/confirm", {
        method: "POST",
        body: { token, password },
      });
      toast.success(t("auth.reset.successToast"));
      router.push("/login");
    } catch (e) {
      const msg = e instanceof Error ? e.message : t("auth.reset.error");
      setError(msg);
      toast.error(msg);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-[440px] flex-col px-6 py-20">
      <div className="rounded-md border border-border bg-card p-8">
        <p className="mb-6 font-mono text-xs uppercase tracking-wider text-muted-foreground">
          {t("auth.reset.cartouche")}
        </p>
        <header className="mb-7 space-y-2">
          <h1 className="font-display text-3xl leading-tight tracking-tight">
            {t("auth.reset.heading")}
          </h1>
          <p className="font-body text-sm text-muted-foreground">
            {t("auth.reset.subtitle")}
          </p>
        </header>

        {!token ? (
          <div className="space-y-4">
            <p className="font-body text-sm text-destructive" aria-live="polite">
              {t("auth.reset.missingToken")}
            </p>
            <Link href="/forgot-password">
              <Button variant="outline" className="w-full">
                {t("auth.reset.requestNew")}
              </Button>
            </Link>
          </div>
        ) : (
          <form className="space-y-4" onSubmit={onSubmit} noValidate>
            <div className="space-y-1.5">
              <label htmlFor="password" className="font-body text-sm font-medium">
                {t("auth.login.password")}
              </label>
              <Input
                id="password"
                type="password"
                placeholder={t("auth.reset.passwordPlaceholder")}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                minLength={12}
                autoComplete="new-password"
                required
              />
            </div>

            <div className="min-h-[1.25rem]" aria-live="polite">
              {error ? (
                <p className="font-body text-sm text-destructive">{error}</p>
              ) : null}
            </div>

            <Button type="submit" className="w-full" disabled={submitting}>
              {submitting ? t("auth.reset.submitting") : t("auth.reset.submit")}
            </Button>
          </form>
        )}
      </div>
    </div>
  );
}
