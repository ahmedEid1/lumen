"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { NeedsAttentionBanner } from "@/components/byok/NeedsAttentionBanner";
import { ValidateButton } from "@/components/byok/ValidateButton";
import { LLMCredentials } from "@/lib/api/endpoints";
import { qk } from "@/lib/query/keys";
import { useAuth } from "@/lib/auth/store";
import { useT } from "@/lib/i18n/provider";
import type { LLMCredentialPublic, LLMValidationStatus } from "@/lib/api/types";

const STATUS_KEY: Record<LLMValidationStatus, Parameters<ReturnType<typeof useT>>[0]> = {
  valid: "byok.status.valid",
  invalid: "byok.status.invalid",
  unvalidated: "byok.status.unvalidated",
  error: "byok.status.invalid",
  needs_attention: "byok.status.needsAttention",
};

/** Masked credential list. Renders last4 + status badge + toggles. Never
 * renders a full key (the API never returns one). */
export function CredentialList({ credentials }: { credentials: LLMCredentialPublic[] }) {
  const t = useT();
  const { token } = useAuth();
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: qk.llmCredentials });

  const patch = useMutation({
    mutationFn: (vars: {
      provider: string;
      body: { enabled?: boolean; is_active?: boolean };
    }) => LLMCredentials.patch(vars.provider, vars.body, token ?? undefined),
    onSuccess: () => void invalidate(),
  });

  const remove = useMutation({
    mutationFn: (provider: string) => LLMCredentials.remove(provider, token ?? undefined),
    onSuccess: () => {
      toast.success(t("byok.deletedToast"));
      void invalidate();
    },
  });

  if (credentials.length === 0) {
    return <p className="text-sm text-muted-foreground">{t("byok.empty")}</p>;
  }

  return (
    <ul className="grid gap-3">
      {credentials.map((c) => (
        <li
          key={c.provider}
          className="grid gap-3 rounded-lg border border-border p-4"
          data-testid={`byok-cred-${c.provider}`}
        >
          <NeedsAttentionBanner status={c.last_validation_status} />
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="grid gap-0.5">
              <span className="font-medium">
                {c.provider} · {c.model}
              </span>
              <span className="text-xs text-muted-foreground">
                ••••{c.last4}{" "}
                <Badge variant="secondary">{t(STATUS_KEY[c.last_validation_status])}</Badge>
              </span>
            </div>
            <div className="flex items-center gap-2">
              <ValidateButton provider={c.provider} onValidated={invalidate} />
              <Button
                type="button"
                variant="ghost"
                onClick={() => remove.mutate(c.provider)}
                disabled={remove.isPending}
              >
                {t("byok.delete")}
              </Button>
            </div>
          </div>
          <div className="flex flex-wrap gap-6">
            <label className="flex items-center gap-2 text-sm">
              <Switch
                checked={c.enabled}
                onCheckedChange={(enabled) => patch.mutate({ provider: c.provider, body: { enabled } })}
                aria-label={t("byok.enabled")}
              />
              {t("byok.enabled")}
            </label>
            <label className="flex items-center gap-2 text-sm">
              <Switch
                checked={c.is_active}
                onCheckedChange={(is_active) =>
                  patch.mutate({ provider: c.provider, body: { is_active } })
                }
                aria-label={t("byok.active")}
              />
              {t("byok.active")}
            </label>
          </div>
        </li>
      ))}
    </ul>
  );
}
