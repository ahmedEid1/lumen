"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/lib/auth/store";
import { ApiError } from "@/lib/api/client";
import { useT } from "@/lib/i18n/provider";

/**
 * Register surface — Workbench repaint.
 *
 * Same single-card pattern as /login: centered card on
 * `bg-background`, mono eyebrow, lime primary CTA at the bottom, no
 * mesh / gradient / glow chrome.
 */
export default function RegisterPage() {
  const router = useRouter();
  const { register } = useAuth();
  const t = useT();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Hydration gate — see /login/page.tsx for the full rationale. tl;dr:
  // gates submit on a useEffect-flipped flag so Playwright's .click()
  // waits for the React handler to bind, otherwise the native form GET
  // races ahead with empty fields (Inputs carry no `name` attr) and
  // hits the API as a 422.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await register({ email, password, full_name: fullName });
      toast.success(t("auth.register.successToast"));
      router.push("/dashboard");
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : t("auth.register.error");
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
          {t("auth.register.cartouche")}
        </p>
        <header className="mb-7 space-y-2">
          <h1 className="font-display text-3xl leading-tight tracking-tight">
            {t("auth.register.heading")}
          </h1>
          <p className="font-body text-sm text-muted-foreground">
            {t("auth.register.subtitle")}
          </p>
        </header>

        <form className="space-y-4" onSubmit={onSubmit} noValidate>
          <div className="space-y-1.5">
            <label htmlFor="full_name" className="font-body text-sm font-medium">
              {t("auth.register.fullName")}
            </label>
            <Input
              id="full_name"
              required
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
            />
          </div>
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
              autoComplete="new-password"
              minLength={12}
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <p className="font-body text-xs text-muted-foreground">
              {t("auth.register.passwordHint")}
            </p>
          </div>

          <div className="min-h-[1.25rem]" aria-live="polite">
            {error ? (
              <p className="font-body text-sm text-destructive">{error}</p>
            ) : null}
          </div>

          <Button type="submit" className="w-full" disabled={submitting || !mounted}>
            {submitting ? t("auth.register.submitting") : t("auth.register.submit")}
          </Button>

          <p className="pt-2 text-center font-body text-sm text-muted-foreground">
            {t("auth.register.haveAccount")}{" "}
            <Link
              href="/login"
              className="font-medium text-foreground underline-offset-4 hover:underline"
            >
              {t("auth.login.submit")}
            </Link>
          </p>
        </form>
      </div>
    </div>
  );
}
