"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Cartouche } from "@/components/lumen/cartouche";
import { Glyph } from "@/components/lumen/glyph";
import { api, ApiError } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/store";
import { useT } from "@/lib/i18n/provider";

type ConfirmResult =
  | { state: "idle" }
  | { state: "loading" }
  | { state: "success"; email: string }
  | { state: "error"; message: string };

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
                : (e instanceof Error ? e.message : t("confirmEmail.generic"));
        setResult({ state: "error", message: msg });
      }
    })();
  }, [params, logout, t]);

  // Pre-split the success template so we can wrap the email in <strong>
  // without losing translation. {EMAIL} is a placeholder that the runtime
  // never substitutes — we split on it instead.
  const successParts = t("confirmEmail.success", { email: "{EMAIL}" }).split(
    "{EMAIL}",
  );

  return (
    <div className="container mx-auto flex max-w-md flex-col items-center px-4 py-20">
      <Cartouche className="mb-5">{t("confirmEmail.cartouche")}</Cartouche>
      <Card className="w-full scroll-paper border-gold/20">
        <CardContent className="space-y-6 pt-8 text-center">
          <header className="flex flex-col items-center gap-3">
            <Glyph
              name="feather"
              size={40}
              mode="tint"
              className="text-gold/85 drop-shadow-[0_0_10px_hsl(var(--gold-leaf)/0.4)]"
            />
            <h1 className="font-display text-2xl font-medium tracking-tight">
              {t("confirmEmail.title")}
            </h1>
          </header>

          {result.state === "loading" && (
            <p className="font-body text-sm text-muted-foreground">
              {t("verifyEmail.checking")}
            </p>
          )}
          {result.state === "success" && (
            <>
              <p className="font-body text-sm text-muted-foreground">
                {successParts[0]}
                <strong className="text-foreground">{result.email}</strong>
                {successParts[1]}
              </p>
              <Button onClick={() => router.push("/login")}>
                {t("auth.login.submit")}
              </Button>
            </>
          )}
          {result.state === "error" && (
            <>
              <p className="font-body text-sm text-destructive">{result.message}</p>
              <Button variant="outline" onClick={() => router.push("/profile")}>
                {t("confirmEmail.backToProfile")}
              </Button>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
