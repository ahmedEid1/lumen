"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { CheckCircle2, AlertCircle } from "lucide-react";
import { AuthCard } from "@/components/ui/auth-card";
import { Button } from "@/components/ui/button";
import { LinkButton } from "@/components/ui/link-button";
import { api, ApiError } from "@/lib/api/client";
import { useT } from "@/lib/i18n/provider";

type Status = "checking" | "success" | "error";

/**
 * Email verification (post-register link target) — Workbench repaint,
 * loop-4 AuthCard migration. Status icon is a Lucide glyph at 20px in
 * the semantic colour. `aria-live="polite"` so the checking → success
 * / error transition is announced. Error branch uses `<LinkButton>`
 * (was the `<Link><Button>` nested-interactive at line 113 in the
 * pre-migration version, audit cross-cutting #3).
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
    <AuthCard cartouche={t("verifyEmail.cartouche")} heading={t("verifyEmail.title")}>
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
          <LinkButton href="/login" variant="outline" className="w-full">
            {t("verifyEmail.goSignIn")}
          </LinkButton>
        )}
      </div>
    </AuthCard>
  );
}
