"use client";

import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { LLMCredentials } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/store";
import { useT } from "@/lib/i18n/provider";

/** Validate the stored key against the provider's registry-fixed base.
 * The result message is server-redacted (no vendor request-ids / key echo).
 */
export function ValidateButton({
  provider,
  onValidated,
}: {
  provider: string;
  onValidated?: () => void;
}) {
  const t = useT();
  const { token } = useAuth();

  const m = useMutation({
    mutationFn: () => LLMCredentials.validate(provider, token ?? undefined),
    onSuccess: (res) => {
      toast.message(res.message);
      onValidated?.();
    },
    onError: (e) => {
      const msg =
        e instanceof ApiError && e.code === "byok.validate_rate_limited"
          ? t("byok.error.rateLimited")
          : e instanceof ApiError
            ? e.message
            : t("byok.error.providerError");
      toast.error(msg);
    },
  });

  return (
    <Button
      type="button"
      variant="secondary"
      onClick={() => m.mutate()}
      disabled={m.isPending}
    >
      {t("byok.validate")}
    </Button>
  );
}
