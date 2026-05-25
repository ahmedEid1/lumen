"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { CheckCircle2, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api, ApiError } from "@/lib/api/client";
import { useT } from "@/lib/i18n/provider";

type Status = "checking" | "success" | "error";

/**
 * Email verification (post-register link target) — Workbench repaint.
 *
 * Same single-card pattern; status icon is a Lucide glyph at 20px in
 * the semantic colour, not a hero badge. `aria-live="polite"` so the
 * checking → success / error transition is announced.
 */
export default function VerifyEmailPage() {
  return (
    <Suspense fallback={<VerifyFallback />}>
      <VerifyEmailInner />
    </Suspense>
  );
}

function VerifyFallback() {
  return (
    <div className="mx-auto flex w-full max-w-[440px] flex-col px-6 py-24">
      <div className="skeleton h-56 w-full" aria-hidden />
    </div>
  );
}

function VerifyEmailInner() {
  const params = useSearchParams();
  const router = useRouter();
  const t = useT();
  const token = params.get("token") ?? "";
  const [status, setStatus] = useState<Status>("checking");
  const [message, setMessage] = useState<string>("");

  useEffect(() => {
    if (!token) {
      setStatus("error");
      setMessage(t("verifyEmail.error.missingToken"));
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        await api("/api/v1/auth/verify/confirm", { method: "POST", body: { token } });
        if (!cancelled) {
          setStatus("success");
          setMessage(t("verifyEmail.success"));
        }
      } catch (err) {
        if (!cancelled) {
          setStatus("error");
          setMessage(err instanceof ApiError ? err.message : t("verifyEmail.error.generic"));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token, t]);

  return (
    <div className="mx-auto flex w-full max-w-[440px] flex-col px-6 py-20">
      <div className="rounded-md border border-border bg-card p-8">
        <p className="mb-6 font-mono text-xs uppercase tracking-wider text-muted-foreground">
          {t("verifyEmail.cartouche")}
        </p>
        <header className="mb-7 space-y-2">
          <h1 className="font-display text-3xl leading-tight tracking-tight">
            {t("verifyEmail.title")}
          </h1>
        </header>

        <div className="space-y-4" aria-live="polite">
          <div className="flex items-start gap-3">
            {status === "success" && (
              <CheckCircle2
                className="mt-0.5 h-5 w-5 flex-none text-primary"
                aria-hidden
              />
            )}
            {status === "error" && (
              <AlertCircle
                className="mt-0.5 h-5 w-5 flex-none text-destructive"
                aria-hidden
              />
            )}
            <p
              className={
                status === "error"
                  ? "font-body text-sm text-destructive"
                  : "font-body text-sm text-muted-foreground"
              }
            >
              {status === "checking" ? t("verifyEmail.checking") : message}
            </p>
          </div>

          {status === "success" && (
            <Button className="w-full" onClick={() => router.push("/dashboard")}>
              {t("verifyEmail.continue")}
            </Button>
          )}
          {status === "error" && (
            <Link href="/login">
              <Button variant="outline" className="w-full">
                {t("verifyEmail.goSignIn")}
              </Button>
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}
