"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { api, ApiError } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/store";

type ConfirmResult =
  | { state: "idle" }
  | { state: "loading" }
  | { state: "success"; email: string }
  | { state: "error"; message: string };

export default function ConfirmEmailChangePage() {
  const params = useSearchParams();
  const router = useRouter();
  const { logout } = useAuth();
  const [result, setResult] = useState<ConfirmResult>({ state: "idle" });

  useEffect(() => {
    const token = params.get("token");
    if (!token) {
      setResult({ state: "error", message: "Missing token" });
      return;
    }
    setResult({ state: "loading" });
    (async () => {
      try {
        const user = await api<{ email: string }>(
          "/api/v1/users/me/email/confirm",
          { method: "POST", body: { token } },
        );
        // Token confirm revoked every refresh token server-side; mirror
        // that on the client so the auth store doesn't keep trying.
        await logout();
        setResult({ state: "success", email: user.email });
        toast.success("Email updated. Sign in with the new address.");
      } catch (e) {
        const code = e instanceof ApiError ? e.code : "";
        const msg =
          code === "email_change.invalid"
            ? "This confirmation link is invalid or has expired."
            : code === "email_change.stale"
              ? "This link is stale — you rotated your password after requesting the change."
              : code === "auth.email_taken"
                ? "That email is now in use by another account."
                : (e instanceof Error ? e.message : "Could not confirm");
        setResult({ state: "error", message: msg });
      }
    })();
  }, [params, logout]);

  return (
    <div className="container mx-auto max-w-md px-4 py-16">
      <Card>
        <CardHeader>
          <CardTitle>Confirm email change</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {result.state === "loading" && <p>Confirming…</p>}
          {result.state === "success" && (
            <>
              <p>
                Your email is now <strong>{result.email}</strong>. Use that
                address next time you sign in.
              </p>
              <Button onClick={() => router.push("/login")}>Sign in</Button>
            </>
          )}
          {result.state === "error" && (
            <>
              <p className="text-destructive">{result.message}</p>
              <Button variant="outline" onClick={() => router.push("/profile")}>
                Back to profile
              </Button>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
