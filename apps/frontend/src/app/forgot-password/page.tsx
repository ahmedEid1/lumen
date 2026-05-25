"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api/client";
import { useT } from "@/lib/i18n/provider";

/**
 * Forgot password — Workbench repaint.
 *
 * After a successful "send", we leave the email input filled and
 * offer a "send again" button instead of resetting the form. This
 * removes the friction case where the user mistyped a character, the
 * link never arrived, and they were forced to re-enter the whole
 * address.
 */
export default function ForgotPasswordPage() {
  const t = useT();
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Hydration gate — see /login/page.tsx for the rationale. The
  // password-reset E2E spec waits 20 s for the reset mail; if the form's
  // native GET fallback fires before hydration the API never sees the
  // POST body, no mail goes out, and the spec times out.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

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
    <div className="mx-auto flex w-full max-w-[440px] flex-col px-6 py-20">
      <div className="rounded-md border border-border bg-card p-8">
        <p className="mb-6 font-mono text-xs uppercase tracking-wider text-muted-foreground">
          {t("auth.forgot.cartouche")}
        </p>
        <header className="mb-7 space-y-2">
          <h1 className="font-display text-3xl leading-tight tracking-tight">
            {t("auth.forgot.heading")}
          </h1>
          <p className="font-body text-sm text-muted-foreground">
            {t("auth.forgot.subtitle")}
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
              placeholder={t("auth.forgot.emailPlaceholder")}
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
                // If the user edits the email after sending, drop the
                // confirmation banner — they're describing a new
                // request.
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
            <Button type="submit" className="w-full" disabled={submitting || !mounted}>
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
      </div>
    </div>
  );
}
