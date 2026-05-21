"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { CheckCircle2, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api, ApiError } from "@/lib/api/client";

type Status = "checking" | "success" | "error";

export default function VerifyEmailPage() {
  const params = useSearchParams();
  const router = useRouter();
  const token = params.get("token") ?? "";
  const [status, setStatus] = useState<Status>("checking");
  const [message, setMessage] = useState<string>("");

  useEffect(() => {
    if (!token) {
      setStatus("error");
      setMessage("Missing token in the link.");
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        await api("/api/v1/auth/verify/confirm", { method: "POST", body: { token } });
        if (!cancelled) {
          setStatus("success");
          setMessage("Your email is verified.");
        }
      } catch (err) {
        if (!cancelled) {
          setStatus("error");
          setMessage(err instanceof ApiError ? err.message : "Could not verify the link.");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  return (
    <div className="container mx-auto flex max-w-md flex-col px-4 py-16">
      <Card>
        <CardHeader>
          <CardTitle>Verify your email</CardTitle>
          <CardDescription>
            {status === "checking" ? "Confirming…" : message}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4 text-center">
          {status === "success" && <CheckCircle2 className="mx-auto h-10 w-10 text-emerald-500" aria-hidden />}
          {status === "error" && <AlertCircle className="mx-auto h-10 w-10 text-destructive" aria-hidden />}
          <div className="flex flex-col gap-2">
            {status === "success" ? (
              <Button onClick={() => router.push("/dashboard")}>Continue to dashboard</Button>
            ) : status === "error" ? (
              <Link href="/login">
                <Button variant="outline" className="w-full">
                  Go to sign in
                </Button>
              </Link>
            ) : null}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
