"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { CheckCircle2, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { api, ApiError } from "@/lib/api/client";
import { useT } from "@/lib/i18n/provider";

type Status = "checking" | "success" | "error";

export default function VerifyEmailPage() {
  return (
    <Suspense fallback={<VerifyFallback />}>
      <VerifyEmailInner />
    </Suspense>
  );
}

function VerifyFallback() {
  return (
    <div className="container mx-auto flex max-w-md flex-col px-6 py-24">
      <div className="surface h-56 animate-pulse" aria-hidden />
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
    <div className="container mx-auto flex max-w-md flex-col items-center px-6 py-24">
      <p className="mb-4 font-body text-xs font-medium uppercase tracking-[0.18em] text-primary">
        {t("verifyEmail.cartouche")}
      </p>
      <Card className="surface w-full">
        <CardContent className="space-y-6 pt-8 text-center">
          {status === "success" && (
            <CheckCircle2 className="mx-auto h-14 w-14 text-primary" aria-hidden />
          )}
          {status === "error" && (
            <AlertCircle className="mx-auto h-14 w-14 text-destructive" aria-hidden />
          )}

          <header className="flex flex-col items-center gap-2">
            <h1 className="font-display text-3xl leading-tight tracking-tight">
              {t("verifyEmail.title")}
            </h1>
            <p className="font-body text-sm text-muted-foreground">
              {status === "checking" ? t("verifyEmail.checking") : message}
            </p>
          </header>

          <div className="flex flex-col gap-2">
            {status === "success" ? (
              <Button onClick={() => router.push("/dashboard")}>
                {t("verifyEmail.continue")}
              </Button>
            ) : status === "error" ? (
              <Link href="/login">
                <Button variant="outline" className="w-full">
                  {t("verifyEmail.goSignIn")}
                </Button>
              </Link>
            ) : null}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
