"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { toast } from "sonner";
import { AuthCard } from "@/components/ui/auth-card";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { PasswordInput } from "@/components/ui/password-input";
import { PasswordStrengthMeter } from "@/components/ui/password-strength-meter";
import { useAuth } from "@/lib/auth/store";
import { ApiError } from "@/lib/api/client";
import { useT } from "@/lib/i18n/provider";
import { useHydrated } from "@/lib/use-hydrated";

/**
 * Register surface — Workbench repaint, loop-4 AuthCard migration.
 * Loop 15 added: PasswordInput (eye toggle), PasswordStrengthMeter,
 * confirm-password with inline mismatch, T&C Checkbox gating submit.
 */
export default function RegisterPage() {
  const router = useRouter();
  const { register } = useAuth();
  const t = useT();
  const hydrated = useHydrated();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [fullName, setFullName] = useState("");
  const [agreed, setAgreed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const mismatch = confirm.length > 0 && confirm !== password;
  const canSubmit =
    hydrated &&
    !submitting &&
    email.length > 0 &&
    password.length >= 12 &&
    confirm === password &&
    agreed;

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
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
          <PasswordInput
            id="password"
            autoComplete="new-password"
            minLength={12}
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <PasswordStrengthMeter value={password} />
          <p className="font-body text-xs text-muted-foreground">
            {t("auth.register.passwordHint")}
          </p>
        </div>
        <div className="space-y-1.5">
          <label
            htmlFor="password_confirm"
            className="font-body text-sm font-medium"
          >
            {t("auth.register.confirmPassword")}
          </label>
          <PasswordInput
            id="password_confirm"
            autoComplete="new-password"
            required
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            aria-invalid={mismatch || undefined}
            aria-describedby={mismatch ? "password_confirm_error" : undefined}
          />
          <div className="min-h-[1rem]" aria-live="polite">
            {mismatch && (
              <p
                id="password_confirm_error"
                className="font-body text-xs text-destructive"
              >
                {t("auth.register.confirmMismatch")}
              </p>
            )}
          </div>
        </div>

        <div className="flex items-start gap-2">
          <Checkbox
            id="terms"
            checked={agreed}
            onCheckedChange={(v) => setAgreed(v === true)}
            className="mt-0.5"
            aria-describedby={!agreed ? "terms_hint" : undefined}
          />
          <label
            htmlFor="terms"
            className="cursor-pointer font-body text-sm text-muted-foreground"
          >
            {t("auth.register.terms.label")}{" "}
            <Link
              href="/"
              className="font-medium text-foreground underline-offset-4 hover:underline"
            >
              {t("auth.register.terms.link")}
            </Link>
            .
          </label>
        </div>

        <div className="min-h-[1.25rem]" aria-live="polite">
          {error ? (
            <p className="font-body text-sm text-destructive">{error}</p>
          ) : null}
        </div>

        <Button
          type="submit"
          className="w-full"
          disabled={!canSubmit}
        >
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
