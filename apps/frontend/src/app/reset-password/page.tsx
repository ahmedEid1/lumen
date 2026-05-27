"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";
import { AuthCard } from "@/components/ui/auth-card";
import { Button } from "@/components/ui/button";
import { LinkButton } from "@/components/ui/link-button";
import { PasswordInput } from "@/components/ui/password-input";
import { api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/store";
import { useT } from "@/lib/i18n/provider";
import { useHydrated } from "@/lib/use-hydrated";

/**
 * Reset password — Workbench repaint, loop-4 AuthCard migration.
 *
 * Token comes from the email link as `?token=…`. We keep the
 * single-card pattern and route errors / missing-token states inline.
 * Missing-token branch now uses `<LinkButton>` instead of the
 * `<Link><Button>` pair the audit flagged at line 92.
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
  const { logout } = useAuth();
  const t = useT();
  const hydrated = useHydrated();
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
      // Backend already revokes all refresh tokens on a successful
      // reset (`users_repo.revoke_all_refresh_tokens`), but the
      // current browser still has React `user` state populated and
      // a (now-orphan) access token cookie. Clear them locally so:
      //   * the login form actually renders on /login (the new
      //     `useEffect(()=>router.replace(next))` would otherwise
      //     auto-forward this signed-in client to /dashboard);
      //   * the user is forced to re-authenticate with the new
      //     credential — which is the whole point of a reset.
      await logout();
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
    <AuthCard
      cartouche={t("auth.reset.cartouche")}
      heading={t("auth.reset.heading")}
      subtitle={t("auth.reset.subtitle")}
    >
      {!token ? (
        <div className="space-y-4">
          <p className="font-body text-sm text-destructive" aria-live="polite">
            {t("auth.reset.missingToken")}
          </p>
          <LinkButton href="/forgot-password" variant="outline" className="w-full">
            {t("auth.reset.requestNew")}
          </LinkButton>
        </div>
      ) : (
        <form className="space-y-4" onSubmit={onSubmit} noValidate>
          <div className="space-y-1.5">
            <label htmlFor="password" className="font-body text-sm font-medium">
              {t("auth.login.password")}
            </label>
            <PasswordInput
              id="password"
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

          <Button type="submit" className="w-full" disabled={submitting || !hydrated}>
            {submitting ? t("auth.reset.submitting") : t("auth.reset.submit")}
          </Button>
        </form>
      )}
    </AuthCard>
  );
}
