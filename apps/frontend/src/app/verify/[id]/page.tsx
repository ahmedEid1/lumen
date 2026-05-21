"use client";

import { use } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Award, CheckCircle2, ShieldX } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api, ApiError } from "@/lib/api/client";

type VerifyOut = {
  certificate_id: string;
  course_id: string;
  course_title: string;
  course_slug: string;
  learner_name: string;
  issued_at: string;
};

export default function VerifyCertificatePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const q = useQuery({
    queryKey: ["verify", id],
    queryFn: () => api<VerifyOut>(`/api/v1/certificates/verify/${encodeURIComponent(id)}`),
    retry: false,
  });

  return (
    <div className="container mx-auto max-w-xl px-4 py-16">
      <Card>
        <CardHeader>
          <CardTitle>Certificate verification</CardTitle>
          <CardDescription>Look up a Lumen certificate by its ID.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {q.isLoading && <p className="text-muted-foreground">Checking…</p>}
          {q.error && (
            <div className="space-y-3 text-center">
              <ShieldX className="mx-auto h-10 w-10 text-destructive" aria-hidden />
              <p>
                {q.error instanceof ApiError && q.error.status === 404
                  ? "No certificate with that ID."
                  : (q.error as Error).message}
              </p>
              <code className="block rounded bg-muted px-3 py-2 text-xs text-muted-foreground">
                {id}
              </code>
              <Link href="/">
                <Button variant="outline">Go home</Button>
              </Link>
            </div>
          )}
          {q.data && (
            <div className="space-y-4 text-center">
              <Award className="mx-auto h-12 w-12 text-emerald-500" aria-hidden />
              <div>
                <p className="text-sm uppercase tracking-wide text-muted-foreground">
                  Certificate issued to
                </p>
                <p className="text-2xl font-semibold">{q.data.learner_name}</p>
              </div>
              <div>
                <p className="text-sm uppercase tracking-wide text-muted-foreground">
                  for completing
                </p>
                <Link href={`/courses/${q.data.course_slug}`} className="text-lg font-medium hover:underline">
                  {q.data.course_title}
                </Link>
              </div>
              <p className="inline-flex items-center gap-2 text-sm text-muted-foreground">
                <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                Issued {new Date(q.data.issued_at).toLocaleDateString()}
              </p>
              <code className="block break-all rounded bg-muted px-3 py-2 text-xs text-muted-foreground">
                {q.data.certificate_id}
              </code>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
