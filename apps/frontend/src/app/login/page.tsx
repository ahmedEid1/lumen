"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { useAuth } from "@/lib/auth/store";
import { ApiError } from "@/lib/api/client";
import { useT } from "@/lib/i18n/provider";

export default function LoginPage() {
  return (
    <Suspense fallback={<LoginFallback />}>
      <LoginForm />
    </Suspense>
  );
}

function LoginFallback() {
  return (
    <div className="container mx-auto flex max-w-md flex-col px-6 py-24">
      <div className="surface h-80 animate-pulse" aria-hidden />
    </div>
  );
}

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next") || "/dashboard";
  const { login } = useAuth();
  const t = useT();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      await login(email, password);
      toast.success(t("auth.login.welcomeToast"));
      router.push(next);
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : t("auth.login.error");
      toast.error(msg);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="container mx-auto flex max-w-md flex-col items-center px-6 py-24">
      <p className="mb-4 font-body text-xs font-medium uppercase tracking-[0.18em] text-primary">
        {t("auth.login.cartouche")}
      </p>
      <Card className="surface w-full">
        <CardContent className="space-y-7 pt-8">
          <header className="flex flex-col items-center gap-2 text-center">
            <h1 className="font-display text-4xl leading-tight tracking-tight">
              {t("auth.login.heading")}
            </h1>
            <p className="font-body text-sm text-muted-foreground">{t("auth.login.subtitle")}</p>
          </header>

          <form className="space-y-4" onSubmit={onSubmit}>
            <div className="space-y-1.5">
              <label htmlFor="email" className="font-body text-sm font-medium">
                {t("auth.login.email")}
              </label>
              <Input
                id="email"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="password" className="font-body text-sm font-medium">
                {t("auth.login.password")}
              </label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
            <Button type="submit" className="w-full" disabled={submitting}>
              {submitting ? t("auth.login.submitting") : t("auth.login.submit")}
            </Button>
            <div className="flex items-center justify-between font-body text-sm">
              <Link
                href="/forgot-password"
                className="text-muted-foreground transition-colors hover:text-foreground"
              >
                {t("auth.forgotPassword")}
              </Link>
              <Link
                href="/register"
                className="font-medium text-primary underline-offset-4 hover:underline"
              >
                {t("auth.register.title")}
              </Link>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
