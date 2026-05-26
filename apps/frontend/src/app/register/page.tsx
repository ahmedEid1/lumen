"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
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
 * Register surface — Workbench repaint, loop-4 AuthCard migration.
 * Chrome lives in `<AuthCard>`; hydration gate in `useHydrated()`.
 * See `apps/frontend/src/app/login/page.tsx` for the load-bearing
 * reason the hydration gate exists.
 */
export default function RegisterPage() {
  const router = useRouter();
  const { register } = useAuth();
  const t = useT();
  const hydrated = useHydrated();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
    <AuthCard
      cartouche={t("auth.register.cartouche")}
      heading={t("auth.register.heading")}
      subtitle={t("auth.register.subtitle")}
    >
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

        <Button type="submit" className="w-full" disabled={submitting || !hydrated}>
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
    </AuthCard>
  );
}
