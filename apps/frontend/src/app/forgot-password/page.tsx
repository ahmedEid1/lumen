"use client";

import { useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { AuthCard } from "@/components/ui/auth-card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api/client";
import { useT } from "@/lib/i18n/provider";
import { useHydrated } from "@/lib/use-hydrated";

/**
 * Forgot password — Workbench repaint, loop-4 AuthCard migration.
 *
 * After a successful "send", we leave the email input filled and
 * offer a "send again" button instead of resetting the form. This
 * removes the friction case where the user mistyped a character, the
 * link never arrived, and they were forced to re-enter the whole
 * address.
 *
 * Hydration gate: see `apps/frontend/src/app/login/page.tsx` for the
 * load-bearing reason — the password-reset E2E spec waits 20 s for
 * the reset mail, so a pre-hydration native GET fallback breaks the
 * test path AND the user flow.
 */
export default function ForgotPasswordPage() {
  const t = useT();
  const hydrated = useHydrated();
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submitRequest() {
    setSubmitting(true);
    setError(null);
    try {
      await api("/api/v1/auth/password-reset/request", {
        method: "POST",
        body: { email },
      });
      setSent(true);
    } catch (e) {
      const msg = e instanceof Error ? e.message : t("auth.forgot.error");
      setError(msg);
      toast.error(msg);
    } finally {
      setSubmitting(false);
    }
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    await submitRequest();
  }

  async function onSendAgain() {
    await submitRequest();
    toast.success(t("auth.forgot.resentToast"));
  }

  const sentParts = t("auth.forgot.sent", { email: "{EMAIL}" }).split("{EMAIL}");

  return (
    <AuthCard
      cartouche={t("auth.forgot.cartouche")}
      heading={t("auth.forgot.heading")}
      subtitle={t("auth.forgot.subtitle")}
    >
      {/* QA-iter1: see comment on the register form — same pre-
          hydration `fill()` race on webkit. */}
      <form
        className="space-y-4"
        onSubmit={onSubmit}
        noValidate
        data-hydrated={hydrated ? "true" : "false"}
      >
        <div className="space-y-1.5">
          <label htmlFor="email" className="font-body text-sm font-medium">
            {t("auth.login.email")}
          </label>
          <Input
            id="email"
            type="email"
            autoComplete="email"
            placeholder={t("auth.forgot.emailPlaceholder")}
            value={email}
            onChange={(e) => {
              setEmail(e.target.value);
              // If the user edits the email after sending, drop the
              // confirmation banner — they're describing a new request.
              if (sent) setSent(false);
            }}
            required
          />
        </div>

        <div className="min-h-[1.25rem]" aria-live="polite">
          {error ? (
            <p className="font-body text-sm text-destructive">{error}</p>
          ) : sent ? (
            <p className="font-body text-sm text-muted-foreground">
              {sentParts[0]}
              <strong className="text-foreground">{email}</strong>
              {sentParts[1]}
            </p>
          ) : null}
        </div>

        {sent ? (
          <Button
            type="button"
            variant="outline"
            className="w-full"
            onClick={onSendAgain}
            disabled={submitting}
          >
            {submitting ? t("auth.forgot.submitting") : t("auth.forgot.sendAgain")}
          </Button>
        ) : (
          <Button type="submit" className="w-full" disabled={submitting || !hydrated}>
            {submitting ? t("auth.forgot.submitting") : t("auth.forgot.submit")}
          </Button>
        )}

        <div className="pt-2 text-center font-body text-sm">
          <Link
            href="/login"
            className="text-muted-foreground transition-colors hover:text-foreground"
          >
            {t("auth.forgot.backToLogin")}
          </Link>
        </div>
      </form>
    </AuthCard>
  );
}
