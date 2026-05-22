"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";
import { AlertCircle, CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api, ApiError } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/store";
import { useT } from "@/lib/i18n/provider";

type ConfirmResult =
  | { state: "idle" }
  | { state: "loading" }
  | { state: "success"; email: string }
  | { state: "error"; message: string };

/**
 * Confirm email change — Workbench repaint.
 *
 * Same operator-card pattern. On success we log the user out
 * (their session is bound to the old email) and route them to
 * /login. On error we surface the typed error code with semantic
 * destructive colour and a "back to profile" outline button.
 */
export default function ConfirmEmailChangePage() {
  const params = useSearchParams();
  const router = useRouter();
  const t = useT();
  const { logout } = useAuth();
  const [result, setResult] = useState<ConfirmResult>({ state: "idle" });

  useEffect(() => {
    const token = params.get("token");
    if (!token) {
      setResult({ state: "error", message: t("confirmEmail.missingToken") });
      return;
    }
    setResult({ state: "loading" });
    (async () => {
      try {
        const user = await api<{ email: string }>(
          "/api/v1/users/me/email/confirm",
          { method: "POST", body: { token } },
        );
        await logout();
        setResult({ state: "success", email: user.email });
        toast.success(t("confirmEmail.successToast"));
      } catch (e) {
        const code = e instanceof ApiError ? e.code : "";
        const msg =
          code === "email_change.invalid"
            ? t("confirmEmail.invalid")
            : code === "email_change.stale"
              ? t("confirmEmail.stale")
              : code === "auth.email_taken"
                ? t("confirmEmail.taken")
                : e instanceof Error
                  ? e.message
                  : t("confirmEmail.generic");
        setResult({ state: "error", message: msg });
      }
    })();
  }, [params, logout, t]);

  // Pre-split the success template so we can wrap the new email
  // in <strong> without losing the translation. {EMAIL} is a
  // placeholder the runtime never substitutes — we split on it.
  const successParts = t("confirmEmail.success", { email: "{EMAIL}" }).split("{EMAIL}");

  return (
    <div className="mx-auto flex w-full max-w-[440px] flex-col px-6 py-20">
      <div className="rounded-md border border-border bg-card p-8">
        <p className="mb-6 font-mono text-xs uppercase tracking-wider text-muted-foreground">
          {t("confirmEmail.cartouche")}
        </p>
        <header className="mb-7 space-y-2">
          <h1 className="font-display text-3xl leading-tight tracking-tight">
            {t("confirmEmail.title")}
          </h1>
        </header>

        <div className="space-y-4" aria-live="polite">
          {result.state === "loading" && (
            <p className="font-body text-sm text-muted-foreground">
              {t("verifyEmail.checking")}
            </p>
          )}
          {result.state === "success" && (
            <>
              <div className="flex items-start gap-3">
                <CheckCircle2
                  className="mt-0.5 h-5 w-5 flex-none text-primary"
                  aria-hidden
                />
                <p className="font-body text-sm text-muted-foreground">
                  {successParts[0]}
                  <strong className="text-foreground">{result.email}</strong>
                  {successParts[1]}
                </p>
              </div>
              <Button className="w-full" onClick={() => router.push("/login")}>
                {t("auth.login.submit")}
              </Button>
            </>
          )}
          {result.state === "error" && (
            <>
              <div className="flex items-start gap-3">
                <AlertCircle
                  className="mt-0.5 h-5 w-5 flex-none text-destructive"
                  aria-hidden
                />
                <p className="font-body text-sm text-destructive">{result.message}</p>
              </div>
              <Button
                variant="outline"
                className="w-full"
                onClick={() => router.push("/profile")}
              >
                {t("confirmEmail.backToProfile")}
              </Button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
