"use client";

import { useQuery } from "@tanstack/react-query";
import { Card } from "@/components/ui/card";
import { CredentialForm } from "@/components/byok/CredentialForm";
import { CredentialList } from "@/components/byok/CredentialList";
import { LLMCredentials, LLMProviders } from "@/lib/api/endpoints";
import { qk } from "@/lib/query/keys";
import { useAuth } from "@/lib/auth/store";
import { useT } from "@/lib/i18n/provider";

/** /profile/model — the BYOK settings tab (S5.15). Provider/model pickers
 * driven from GET /llm-providers; write-only masked key; validate; consent
 * toggle. NO base-url field anywhere (DR-17). */
export default function ModelSettingsPage() {
  const t = useT();
  const { token, ready } = useAuth();

  const providersQ = useQuery({
    queryKey: qk.llmProviders,
    queryFn: () => LLMProviders.list(token ?? undefined),
    enabled: ready,
  });

  const credentialsQ = useQuery({
    queryKey: qk.llmCredentials,
    queryFn: () => LLMCredentials.list(token ?? undefined),
    enabled: ready,
  });

  const providers = providersQ.data?.providers ?? [];

  return (
    <main className="mx-auto grid max-w-2xl gap-6 px-4 py-10">
      <header className="grid gap-1">
        <h1 className="text-2xl font-semibold">{t("byok.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("byok.subtitle")}</p>
      </header>

      <Card className="grid gap-6 p-6">
        {providers.length > 0 && <CredentialForm providers={providers} />}
      </Card>

      <section className="grid gap-3">
        <CredentialList credentials={credentialsQ.data ?? []} />
      </section>
    </main>
  );
}
