"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { useAuth } from "@/lib/auth/store";
import { ApiError } from "@/lib/api/client";
import { useT } from "@/lib/i18n/provider";

export default function RegisterPage() {
  const router = useRouter();
  const { register } = useAuth();
  const t = useT();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      await register({ email, password, full_name: fullName });
      toast.success(t("auth.register.successToast"));
      router.push("/dashboard");
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : t("auth.register.error");
      toast.error(msg);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="container mx-auto flex max-w-md flex-col items-center px-6 py-24">
      <p className="mb-4 font-body text-xs font-medium uppercase tracking-[0.18em] text-primary">
        {t("auth.register.cartouche")}
      </p>
      <Card className="surface w-full">
        <CardContent className="space-y-7 pt-8">
          <header className="flex flex-col items-center gap-2 text-center">
            <h1 className="font-display text-4xl leading-tight tracking-tight">
              {t("auth.register.heading")}
            </h1>
            <p className="font-body text-sm text-muted-foreground">{t("auth.register.subtitle")}</p>
          </header>

          <form className="space-y-4" onSubmit={onSubmit}>
            <div className="space-y-1.5">
              <label htmlFor="full_name" className="font-body text-sm font-medium">
                {t("auth.register.fullName")}
              </label>
              <Input
                id="full_name"
                required
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
              />
            </div>
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
                autoComplete="new-password"
                minLength={12}
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
              <p className="font-body text-xs text-muted-foreground">
                {t("auth.register.passwordHint")}
              </p>
            </div>
            <Button type="submit" className="w-full" disabled={submitting}>
              {submitting ? t("auth.register.submitting") : t("auth.register.submit")}
            </Button>
            <p className="text-center font-body text-sm text-muted-foreground">
              {t("auth.register.haveAccount")}{" "}
              <Link
                href="/login"
                className="font-medium text-primary underline-offset-4 hover:underline"
              >
                {t("auth.login.submit")}
              </Link>
            </p>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
