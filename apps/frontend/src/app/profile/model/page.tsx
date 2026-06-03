"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { Card } from "@/components/ui/card";
import { CredentialForm } from "@/components/byok/CredentialForm";
import { CredentialList } from "@/components/byok/CredentialList";
import { LLMCredentials, LLMProviders } from "@/lib/api/endpoints";
import { qk } from "@/lib/query/keys";
import { useAuth } from "@/lib/auth/store";
import { useT } from "@/lib/i18n/provider";

/** /profile/model — the BYOK settings tab (S5.15). Provider/model pickers
 * driven from GET /llm-providers; write-only masked key; validate; consent
 * toggle. NO base-url field anywhere (DR-17).
 *
 * Gate-B/C fixes: requires auth (mirrors /profile — this page used to render
 * its full form to signed-out visitors) and gates on the server's
 * `byok_enabled` flag so a flag-off deploy shows an unavailable notice
 * instead of a form whose submit can only 403. */
export default function ModelSettingsPage() {
  const t = useT();
  const router = useRouter();
  const { user, token, ready } = useAuth();

  useEffect(() => {
    if (ready && !user) router.replace("/login?next=/profile/model");
  }, [ready, user, router]);

  const authed = ready && !!user;

  const providersQ = useQuery({
    queryKey: qk.llmProviders,
    queryFn: () => LLMProviders.list(token ?? undefined),
    enabled: authed,
  });

  const byokEnabled = providersQ.data?.byok_enabled ?? false;

  const credentialsQ = useQuery({
    queryKey: qk.llmCredentials,
    queryFn: () => LLMCredentials.list(token ?? undefined),
    enabled: authed && byokEnabled,
  });

  if (!authed) {
    // Redirecting (or auth still resolving) — render nothing rather than
    // an anonymous flash of the settings form.
    return null;
  }

  const providers = providersQ.data?.providers ?? [];

  return (
    <main className="mx-auto grid max-w-2xl gap-6 px-4 py-10">
      <header className="grid gap-1">
        <h1 className="text-2xl font-semibold">{t("byok.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("byok.subtitle")}</p>
      </header>

      {providersQ.isSuccess && !byokEnabled ? (
        <Card className="p-6">
          <p className="text-sm text-muted-foreground">{t("byok.unavailable")}</p>
        </Card>
      ) : (
        <>
          <Card className="grid gap-6 p-6">
            {providers.length > 0 && <CredentialForm providers={providers} />}
          </Card>

          <section className="grid gap-3">
            <CredentialList credentials={credentialsQ.data ?? []} />
          </section>
        </>
      )}
    </main>
  );
}
