"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { Sparkles } from "lucide-react";
import { toast } from "sonner";
import { AuthCard } from "@/components/ui/auth-card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PasswordInput } from "@/components/ui/password-input";
import { useAuth } from "@/lib/auth/store";
import { safeNext } from "@/lib/auth/safe-next";
import { ApiError } from "@/lib/api/client";
import { useT } from "@/lib/i18n/provider";
import { useHydrated } from "@/lib/use-hydrated";

// QA-loop iter 1 — public demo credentials are seeded by
// `apps/backend/app/seeds/demo.py` and intentionally documented in
// the README. `/demo` redirects through `/login?demo=1` so the
// portfolio visitor doesn't have to look them up.
const DEMO_EMAIL = "demo@lumen.test";
const DEMO_PASSWORD = "Demo!2026";

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
  const next = safeNext(params.get("next"));
  const isDemo = params.get("demo") === "1";
  const { login, user, ready } = useAuth();
  const t = useT();
  const hydrated = useHydrated();
  const [email, setEmail] = useState(isDemo ? DEMO_EMAIL : "");
  const [password, setPassword] = useState(isDemo ? DEMO_PASSWORD : "");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // QA-loop iter 1 — Codex rescue + webkit E2E fix.
  //
  // When an already-signed-in user arrives at /login (especially via
  // the new /demo redirect), forward them to `next` without showing
  // the form. Without this, a signed-in visitor clicking the demo
  // CTA would be invited to sign in as the demo learner — clobbering
  // their real session.
  //
  // The check is intentionally *one-shot at first ready=true*: we
  // snapshot `user` the moment hydration completes, and only redirect
  // if they were ALREADY signed in. Later transitions to signed-in
  // (e.g., the form's own `await login()` populating user state)
  // belong to the form's `router.push(next)`, not to this effect.
  // Earlier (re-firing on every `user` change) the effect raced with
  // the form's router.push on webkit specifically — the CI E2E
  // `tutor-citations` spec got stuck at /login through 3 retries on
  // webkit only, with both navigations targeting the same URL but
  // neither one actually taking. Once-on-ready avoids the race
  // entirely.
  const alreadySignedInRef = useRef<boolean | null>(null);
  useEffect(() => {
    if (!ready) return;
    if (alreadySignedInRef.current === null) {
      alreadySignedInRef.current = !!user;
    }
    if (alreadySignedInRef.current && user) {
      router.replace(next);
    }
  }, [ready, user, next, router]);
  const alreadySignedIn =
    ready && alreadySignedInRef.current === true && !!user;

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

  if (alreadySignedIn) {
    // The effect above is forwarding the user to `next`. Render the
    // same skeleton the Suspense fallback uses so there's no flash
    // of the login form during the redirect.
    return <LoginFallback />;
  }
  return (
    <AuthCard
      cartouche={t("auth.login.cartouche")}
      heading={isDemo ? t("auth.login.demoHeading") : t("auth.login.heading")}
      subtitle={isDemo ? t("auth.login.demoSubtitle") : t("auth.login.subtitle")}
    >
      {isDemo && (
        <div
          className="mb-4 flex items-start gap-2 rounded-md border border-border bg-muted/30 p-3 font-body text-sm text-muted-foreground"
          data-testid="login-demo-notice"
        >
          <Sparkles
            className="mt-0.5 h-4 w-4 shrink-0 text-primary"
            aria-hidden
          />
          <p>
            {t("auth.login.demoNotice")}{" "}
            <span className="font-mono text-foreground">{DEMO_EMAIL}</span>
            {" · "}
            <span className="font-mono text-foreground">{DEMO_PASSWORD}</span>
          </p>
        </div>
      )}
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
          <PasswordInput
            id="password"
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
