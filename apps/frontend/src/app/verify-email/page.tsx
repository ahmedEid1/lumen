"use client";

import { Suspense, useEffect, useRef, useState } from "react";
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
  // QA-iter1 fix: `calledRef` is the idempotency guard (Loop 15 added
  // it so React 19 strict-mode double-invoke can't burn the token by
  // submitting it twice). We also use an `unmountedRef` instead of
  // an effect-local `cancelled` flag, because the effect-local flag
  // races against strict-mode's "mount → cleanup → re-mount" cycle:
  //   1. effect runs → calledRef=true, fires API, returns cleanup
  //   2. strict-mode cleanup runs → sets THAT effect's cancelled=true
  //   3. effect re-runs → calledRef=true, returns early
  //   4. API resolves → `!cancelled` is FALSE → no setState
  //   → page stuck on "Confirming…" forever.
  // The unmountedRef is set only by the empty-deps unmount effect, so
  // it stays false through strict-mode's re-mount cycle and only flips
  // when the component is genuinely going away.
  const calledRef = useRef(false);
  const unmountedRef = useRef(false);
  useEffect(() => {
    unmountedRef.current = false;
    return () => {
      unmountedRef.current = true;
    };
  }, []);

  // Capture `t` in a ref so the verify effect can read the latest
  // locale-bound formatter without re-running on every locale change.
  // The effect itself only depends on `token`.
  const tRef = useRef(t);
  useEffect(() => {
    tRef.current = t;
  }, [t]);

  useEffect(() => {
    if (!token) {
      setStatus("error");
      setMessage(tRef.current("verifyEmail.error.missingToken"));
      return;
    }
    if (calledRef.current) return;
    calledRef.current = true;
    (async () => {
      try {
        await api("/api/v1/auth/verify/confirm", { method: "POST", body: { token } });
        if (!unmountedRef.current) {
          setStatus("success");
          setMessage(tRef.current("verifyEmail.success"));
        }
      } catch (err) {
        if (!unmountedRef.current) {
          setStatus("error");
          setMessage(
            err instanceof ApiError
              ? err.message
              : tRef.current("verifyEmail.error.generic"),
          );
        }
      }
    })();
  }, [token]);

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
