"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api/client";

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<ResetFallback />}>
      <ResetForm />
    </Suspense>
  );
}

function ResetFallback() {
  return (
    <div className="container mx-auto flex max-w-md flex-col px-4 py-16">
      <div className="h-56 animate-pulse rounded-xl bg-muted" aria-hidden />
    </div>
  );
}

function ResetForm() {
  const router = useRouter();
  const params = useSearchParams();
  const token = params.get("token") ?? "";
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!token) {
      toast.error("Missing reset token");
      return;
    }
    setSubmitting(true);
    try {
      await api("/api/v1/auth/password-reset/confirm", {
        method: "POST",
        body: { token, password },
      });
      toast.success("Password updated — please sign in");
      router.push("/login");
    } catch (e: any) {
      toast.error(e?.message ?? "Could not reset password");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="container mx-auto flex max-w-md flex-col px-4 py-16">
      <Card>
        <CardHeader>
          <CardTitle>Choose a new password</CardTitle>
          <CardDescription>Links expire 30 minutes after being requested.</CardDescription>
        </CardHeader>
        <CardContent>
          {!token ? (
            <p className="text-sm text-muted-foreground">
              This page needs a reset token in the URL.{" "}
              <Link href="/forgot-password" className="text-primary hover:underline">
                Request a new one
              </Link>
              .
            </p>
          ) : (
            <form className="space-y-4" onSubmit={onSubmit}>
              <Input
                type="password"
                placeholder="New password (≥ 12 chars)"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                minLength={12}
                autoComplete="new-password"
                required
              />
              <Button type="submit" className="w-full" disabled={submitting}>
                {submitting ? "Updating…" : "Set new password"}
              </Button>
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
