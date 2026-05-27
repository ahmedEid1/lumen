"use client";

import { useQuery } from "@tanstack/react-query";
import { RuntimeFlagsApi, type RuntimeFlags } from "@/lib/api/endpoints";
import { qk } from "@/lib/query/keys";

/**
 * L20.5 — Runtime feature flags.
 *
 * `useRuntimeFlags()` reads `/api/v1/runtime-flags` once per page,
 * caches for 60s, and re-validates on focus. Defaults to all-off
 * (the safe pre-flip state) while the request is in flight so a
 * page's first paint doesn't accidentally unlock a feature.
 *
 * The L21b flag-flip PR will toggle `tutor_streaming` on by writing
 * to the same Settings field (L21-Sec will additionally add a Redis
 * override layer so an admin can flip without a redeploy). Callers
 * gate streaming UI with `flags.tutor_streaming` so the codepaths
 * stay dormant until that flip.
 */

const DEFAULT_FLAGS: RuntimeFlags = {
  tutor_streaming: false,
};

export function useRuntimeFlags(): RuntimeFlags {
  const q = useQuery({
    queryKey: qk.runtimeFlags,
    queryFn: () => RuntimeFlagsApi.get(),
    staleTime: 60_000,
    gcTime: 5 * 60_000,
    refetchOnWindowFocus: true,
    retry: 1,
  });
  return q.data ?? DEFAULT_FLAGS;
}
