"use client";

import { useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Cartouche } from "@/components/lumen/cartouche";
import { Glyph } from "@/components/lumen/glyph";
import { api } from "@/lib/api/client";
import { useT } from "@/lib/i18n/provider";

export default function ForgotPasswordPage() {
  const t = useT();
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      await api("/api/v1/auth/password-reset/request", { method: "POST", body: { email } });
      setSent(true);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t("auth.forgot.error"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="container mx-auto flex max-w-md flex-col items-center px-4 py-20">
      <Cartouche className="mb-5">{t("auth.forgot.cartouche")}</Cartouche>
      <Card className="w-full scroll-paper border-gold/20">
        <CardContent className="space-y-6 pt-8">
          <header className="flex flex-col items-center gap-3 text-center">
            <Glyph
              name="feather"
              size={42}
              mode="tint"
              className="text-gold/85 drop-shadow-[0_0_10px_hsl(var(--gold-leaf)/0.4)]"
            />
            <h1 className="font-display text-3xl font-medium tracking-tight">
              {t("auth.forgot.heading")}
            </h1>
            <p className="font-body text-sm text-muted-foreground">
              {t("auth.forgot.subtitle")}
            </p>
          </header>

          {sent ? (
            <p className="font-body text-sm text-muted-foreground">
              {(() => {
                const parts = t("auth.forgot.sent", { email: "{EMAIL}" }).split("{EMAIL}");
                return (
                  <>
                    {parts[0]}
                    <strong className="text-foreground">{email}</strong>
                    {parts[1]}
                  </>
                );
              })()}
              <br />
              <Link
                href="/login"
                className="text-gold underline-offset-4 hover:underline"
              >
                {t("auth.forgot.backToLogin")}
              </Link>
            </p>
          ) : (
            <form className="space-y-4" onSubmit={onSubmit}>
              <Input
                type="email"
                autoComplete="email"
                placeholder={t("auth.forgot.emailPlaceholder")}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="border-gold/25 bg-background/60 focus-visible:border-gold/60"
              />
              <Button type="submit" className="w-full" disabled={submitting}>
                {submitting ? t("auth.forgot.submitting") : t("auth.forgot.submit")}
              </Button>
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
