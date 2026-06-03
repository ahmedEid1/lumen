"use client";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useT } from "@/lib/i18n/provider";
import type { LLMProvider } from "@/lib/api/types";

/** Provider → model cascade, both driven from GET /llm-providers (S5.15).
 * The frontend never hard-codes providers/models (FR-BYOK-20). There is
 * deliberately NO base-url field anywhere. */
export function ProviderSelect({
  providers,
  provider,
  model,
  onProviderChange,
  onModelChange,
}: {
  providers: LLMProvider[];
  provider: string;
  model: string;
  onProviderChange: (p: string) => void;
  onModelChange: (m: string) => void;
}) {
  const t = useT();
  const selected = providers.find((p) => p.provider === provider);
  const models = selected?.models ?? [];

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <label className="grid gap-1.5 text-sm">
        <span className="font-medium">{t("byok.provider")}</span>
        <Select value={provider} onValueChange={onProviderChange}>
          <SelectTrigger aria-label={t("byok.provider")}>
            <SelectValue placeholder={t("byok.provider")} />
          </SelectTrigger>
          <SelectContent>
            {providers.map((p) => (
              <SelectItem key={p.provider} value={p.provider}>
                {p.display_name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </label>

      <label className="grid gap-1.5 text-sm">
        <span className="font-medium">{t("byok.model")}</span>
        <Select value={model} onValueChange={onModelChange} disabled={!provider}>
          <SelectTrigger aria-label={t("byok.model")}>
            <SelectValue placeholder={t("byok.model")} />
          </SelectTrigger>
          <SelectContent>
            {models.map((m) => (
              <SelectItem key={m} value={m}>
                {m}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </label>
    </div>
  );
}
