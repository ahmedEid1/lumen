"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { CheckCircle2, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Cartouche } from "@/components/lumen/cartouche";
import { Glyph } from "@/components/lumen/glyph";
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
    <div className="container mx-auto flex max-w-md flex-col px-4 py-20">
      <div className="h-56 animate-pulse rounded-md border border-border bg-card/40" aria-hidden />
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
    <div className="container mx-auto flex max-w-md flex-col items-center px-4 py-20">
      <Cartouche className="mb-5">{t("verifyEmail.cartouche")}</Cartouche>
      <Card className="w-full scroll-paper border-gold/20">
        <CardContent className="space-y-6 pt-8 text-center">
          <header className="flex flex-col items-center gap-3">
            <Glyph
              name="eye"
              size={40}
              mode="tint"
              className="text-gold/85 drop-shadow-[0_0_10px_hsl(var(--gold-leaf)/0.4)]"
            />
            <h1 className="font-display text-2xl font-medium tracking-tight">
              {t("verifyEmail.title")}
            </h1>
            <p className="font-body text-sm text-muted-foreground">
              {status === "checking" ? t("verifyEmail.checking") : message}
            </p>
          </header>

          {status === "success" && (
            <CheckCircle2
              className="mx-auto h-10 w-10 text-gold"
              aria-hidden
            />
          )}
          {status === "error" && (
            <AlertCircle className="mx-auto h-10 w-10 text-destructive" aria-hidden />
          )}
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
