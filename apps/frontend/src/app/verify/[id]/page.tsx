"use client";

import { use } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Award, CheckCircle2, ShieldCheck, ShieldX } from "lucide-react";
import { AuthCard } from "@/components/ui/auth-card";
import { LinkButton } from "@/components/ui/link-button";
import { api, ApiError } from "@/lib/api/client";
import { useT } from "@/lib/i18n/provider";

type VerifyOut = {
  certificate_id: string;
  course_id: string;
  course_title: string;
  course_slug: string;
  learner_name: string;
  issued_at: string;
};

// Phase E5 — the OB3 verify endpoint returns a tiny summary. We don't
// fetch the full JSON-LD credential into the page because the Open
// Badge link in the dashboard already exposes it; this page is for
// the human checking "did Lumen really issue this?", not for ingesting
// the credential into a wallet.
type CredentialVerifyOut = {
  valid: boolean;
  issuer: string | null;
  achievement_name: string | null;
  learner_name: string | null;
};

/**
 * Certificate verification — Workbench repaint.
 *
 * Single centered card, mono eyebrow, no gold/lapis chrome. The
 * certificate ID is rendered in JBM mono inside a muted code block,
 * because it is the load-bearing artifact on this surface.
 */
export default function VerifyCertificatePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const t = useT();
  const q = useQuery({
    queryKey: ["verify", id],
    queryFn: () => api<VerifyOut>(`/api/v1/certificates/verify/${encodeURIComponent(id)}`),
    retry: false,
  });
  // Side query: the OB3 verify endpoint runs a signature check the
  // legacy verify endpoint can't. We render its result inline once
  // the primary lookup succeeds. Failure here is non-fatal — older
  // certificates issued before Phase E5 may not have a stored
  // credential (the backend mints on-the-fly), so the worst case is
  // a missing signature badge, not a broken page.
  const credQ = useQuery({
    queryKey: ["credentialVerify", id],
    queryFn: () =>
      api<CredentialVerifyOut>(
        `/api/v1/credentials/${encodeURIComponent(id)}/verify`,
      ),
    enabled: !!q.data,
    retry: false,
  });

  return (
    <AuthCard
      cartouche={t("verifyCert.cartouche")}
      heading={t("verifyCert.title")}
      subtitle={t("verifyCert.subtitle")}
      className="max-w-[520px]"
    >
      <div aria-live="polite">
        {q.isLoading && (
          <p className="font-body text-sm text-muted-foreground">
            {t("verifyCert.checking")}
          </p>
        )}

        {q.error && (
          <div className="space-y-4">
            <div className="flex items-start gap-3">
              <ShieldX
                className="mt-0.5 h-5 w-5 flex-none text-destructive"
                aria-hidden
              />
              <p className="font-body text-sm text-destructive">
                {q.error instanceof ApiError && q.error.status === 404
                  ? t("verifyCert.notFound")
                  : (q.error as Error).message}
              </p>
            </div>
            <code className="block break-all rounded-md border border-border bg-muted px-3 py-2 font-mono text-xs text-muted-foreground">
              {id}
            </code>
            <LinkButton href="/" variant="outline" className="w-full">
              {t("verifyCert.goHome")}
            </LinkButton>
          </div>
        )}

          {q.data && (
            <div className="space-y-5">
              <div className="flex items-center gap-3 border-b border-border pb-5">
                <Award className="h-5 w-5 flex-none text-primary" aria-hidden />
                <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
                  {t("verifyCert.issuedTo")}
                </p>
              </div>
              <p className="font-display text-2xl leading-tight tracking-tight">
                {q.data.learner_name}
              </p>
              <div className="space-y-1">
                <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
                  {t("verifyCert.forCompleting")}
                </p>
                <Link
                  href={`/courses/${q.data.course_slug}`}
                  className="font-display text-lg leading-tight text-foreground underline-offset-4 hover:underline"
                >
                  {q.data.course_title}
                </Link>
              </div>
              <p className="inline-flex items-center gap-2 font-body text-sm text-muted-foreground">
                <CheckCircle2 className="h-4 w-4 text-primary" aria-hidden />
                {t("verifyCert.issuedOn", {
                  date: new Date(q.data.issued_at).toLocaleDateString(),
                })}
              </p>
              <code className="block break-all rounded-md border border-border bg-muted px-3 py-2 font-mono text-xs text-muted-foreground">
                {q.data.certificate_id}
              </code>
              {/* Phase E5 — OB3 signature panel. Shown only when the
                  credential-verify endpoint returns; older certs
                  predating E5 simply render without this row. */}
              {credQ.data && (
                <div className="flex items-center justify-between gap-3 border-t border-border pt-4">
                  <div className="flex items-center gap-2">
                    {credQ.data.valid ? (
                      <ShieldCheck
                        className="h-4 w-4 text-primary"
                        aria-hidden
                      />
                    ) : (
                      <ShieldX
                        className="h-4 w-4 text-destructive"
                        aria-hidden
                      />
                    )}
                    <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
                      {credQ.data.valid
                        ? t("verifyCert.signatureValid")
                        : t("verifyCert.signatureInvalid")}
                    </p>
                  </div>
                  <a
                    href={`/api/v1/credentials/${encodeURIComponent(id)}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="font-mono text-xs uppercase tracking-wider text-muted-foreground underline-offset-4 transition-colors duration-[160ms] hover:text-foreground hover:underline"
                  >
                    {t("verifyCert.openCredential")}
                  </a>
                </div>
              )}
            </div>
          )}
      </div>
    </AuthCard>
  );
}
