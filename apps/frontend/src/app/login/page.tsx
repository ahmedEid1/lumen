"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { toast } from "sonner";
import { AuthCard } from "@/components/ui/auth-card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/lib/auth/store";
import { ApiError } from "@/lib/api/client";
import { useT } from "@/lib/i18n/provider";
import { useHydrated } from "@/lib/use-hydrated";

/**
 * Sign-in surface — Workbench repaint, loop-4 AuthCard migration.
 *
 * Chrome lives in `<AuthCard>`; hydration gate lives in `useHydrated()`
 * (was four copy-pasted paragraphs across login/register/forgot/reset
 * — see AUDIT.md cross-cutting #1). The submit button's disabled gate
 * is the load-bearing reason the hook exists: Playwright's click()
 * auto-waits for `disabled=false`, which only flips post-hydration
 * once the React onSubmit handler is bound; without it the native
 * form-submit fallback GETs `/login?` with empty fields and the URL
 * never advances to /dashboard.
 */
export default function LoginPage() {
  return (
    <Suspense fallback={<LoginFallback />}>
      <LoginForm />
    </Suspense>
  );
}

function LoginFallback() {
  return (
    <div className="mx-auto flex w-full max-w-[440px] flex-col px-6 py-24">
      <div className="skeleton h-80 w-full" aria-hidden />
    </div>
  );
}

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next") || "/dashboard";
  const { login } = useAuth();
  const t = useT();
  const hydrated = useHydrated();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await login(email, password);
      toast.success(t("auth.login.welcomeToast"));
      router.push(next);
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : t("auth.login.error");
      setError(msg);
      toast.error(msg);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthCard
      cartouche={t("auth.login.cartouche")}
      heading={t("auth.login.heading")}
      subtitle={t("auth.login.subtitle")}
    >
      <form className="space-y-4" onSubmit={onSubmit} noValidate>
        <div className="space-y-1.5">
          <label htmlFor="email" className="font-body text-sm font-medium">
            {t("auth.login.email")}
          </label>
          <Input
            id="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <div className="space-y-1.5">
          <label htmlFor="password" className="font-body text-sm font-medium">
            {t("auth.login.password")}
          </label>
          <Input
            id="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>

        <div className="min-h-[1.25rem]" aria-live="polite">
          {error ? (
            <p className="font-body text-sm text-destructive">{error}</p>
          ) : null}
        </div>

        <Button type="submit" className="w-full" disabled={submitting || !hydrated}>
          {submitting ? t("auth.login.submitting") : t("auth.login.submit")}
        </Button>

        <div className="flex items-center justify-between pt-2 font-body text-sm">
          <Link
            href="/forgot-password"
            className="text-muted-foreground transition-colors hover:text-foreground"
          >
            {t("auth.forgotPassword")}
          </Link>
          <Link
            href="/register"
            className="font-medium text-foreground underline-offset-4 hover:underline"
          >
            {t("auth.register.title")}
          </Link>
        </div>
      </form>
    </AuthCard>
  );
}
