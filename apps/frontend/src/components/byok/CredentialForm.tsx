"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { PasswordInput } from "@/components/ui/password-input";
import { Switch } from "@/components/ui/switch";
import { ProviderSelect } from "@/components/byok/ProviderSelect";
import { LLMCredentials } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/client";
import { qk } from "@/lib/query/keys";
import { useAuth } from "@/lib/auth/store";
import { useT } from "@/lib/i18n/provider";
import type { LLMProvider } from "@/lib/api/types";

/** Add/replace a BYOK credential. Write-only password key input (never
 * pre-filled), provider→model cascade from the registry, allow-fallback
 * consent toggle. There is NO base-url / endpoint field (DR-17). */
export function CredentialForm({ providers }: { providers: LLMProvider[] }) {
  const t = useT();
  const { token } = useAuth();
  const qc = useQueryClient();

  const first = providers[0];
  const [provider, setProvider] = useState(first?.provider ?? "");
  const [model, setModel] = useState(first?.models[0] ?? "");
  const [apiKey, setApiKey] = useState("");
  const [allowFallback, setAllowFallback] = useState(true);

  const onProviderChange = (p: string) => {
    setProvider(p);
    const next = providers.find((x) => x.provider === p);
    setModel(next?.models[0] ?? "");
  };

  // When the provider switches, the previously-selected model item unmounts
  // and Radix Select fires onValueChange("") for the now-orphaned value —
  // which would clobber the first/only model we just default-selected and
  // leave Save dishonestly disabled (C1). There is no empty model option a
  // real user can pick, so an empty callback is always that stale reset:
  // ignore it and keep the controlled default.
  const onModelChange = (m: string) => {
    if (m) setModel(m);
  };

  const save = useMutation({
    mutationFn: () =>
      LLMCredentials.upsert(
        provider,
        { model, api_key: apiKey, allow_platform_fallback: allowFallback },
        token ?? undefined,
      ),
    onSuccess: () => {
      setApiKey(""); // never retain the key in the form after a save
      toast.success(t("byok.savedToast"));
      void qc.invalidateQueries({ queryKey: qk.llmCredentials });
    },
    onError: (e) => {
      toast.error(e instanceof ApiError ? e.message : t("byok.error.providerError"));
    },
  });

  return (
    <form
      className="grid gap-4"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <ProviderSelect
        providers={providers}
        provider={provider}
        model={model}
        onProviderChange={onProviderChange}
        onModelChange={onModelChange}
      />

      <label className="grid gap-1.5 text-sm">
        <span className="font-medium">{t("byok.apiKey")}</span>
        <PasswordInput
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          autoComplete="off"
          placeholder="sk-…"
          aria-label={t("byok.apiKey")}
        />
        <span className="text-muted-foreground text-xs">{t("byok.apiKey.writeOnly")}</span>
      </label>

      <label className="flex cursor-pointer items-center justify-between gap-3 text-sm">
        <span>{t("byok.allowFallback")}</span>
        <Switch
          checked={allowFallback}
          onCheckedChange={setAllowFallback}
          aria-label={t("byok.allowFallback")}
        />
      </label>

      <div>
        <Button type="submit" disabled={save.isPending || !provider || !model || !apiKey}>
          {t("byok.save")}
        </Button>
      </div>
    </form>
  );
}
