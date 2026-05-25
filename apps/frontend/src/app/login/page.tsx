"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/lib/auth/store";
import { ApiError } from "@/lib/api/client";
import { useT } from "@/lib/i18n/provider";

/**
 * Sign-in surface — Workbench repaint.
 *
 * Operator-login feel: one centered card on `bg-background`, a single
 * lime CTA, no mesh / gradient / glow chrome. Eyebrow uses the mono
 * label treatment (font-mono uppercase tracking-wider text-xs
 * text-muted-foreground); the `.cartouche` i18n key name is legacy.
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
    <div className="mx-auto flex w-full max-w-[440px] flex-col px-6 py-20">
      <div className="rounded-md border border-border bg-card p-8">
        <p className="mb-6 font-mono text-xs uppercase tracking-wider text-muted-foreground">
          {t("auth.login.cartouche")}
        </p>
        <header className="mb-7 space-y-2">
          <h1 className="font-display text-3xl leading-tight tracking-tight">
            {t("auth.login.heading")}
          </h1>
          <p className="font-body text-sm text-muted-foreground">
            {t("auth.login.subtitle")}
          </p>
        </header>

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

          <Button type="submit" className="w-full" disabled={submitting}>
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
      </div>
    </div>
  );
}
