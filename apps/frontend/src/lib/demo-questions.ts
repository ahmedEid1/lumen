"use client";

import { useQuery } from "@tanstack/react-query";
import {
  DemoQuestionsApi,
  type DemoQuestionLibrary,
} from "@/lib/api/endpoints";
import { qk } from "@/lib/query/keys";

/**
 * L20.6 — curated demo-question library.
 *
 * `useDemoQuestions(courseSlug)` reads the questions scoped to the
 * given course (omit for the full library). 5-minute stale window —
 * the library version bumps rarely; we don't need to keep re-fetching.
 *
 * The L22 chip rail consumes this. The canonical id (the one the
 * screencap records against) is returned alongside the list so the
 * chip rail can render the canonical question first when present.
 */
export function useDemoQuestions(courseSlug?: string) {
  return useQuery<DemoQuestionLibrary>({
    queryKey: qk.demoQuestions(courseSlug),
    queryFn: () => DemoQuestionsApi.list(courseSlug),
    staleTime: 5 * 60_000,
    gcTime: 30 * 60_000,
    refetchOnWindowFocus: false,
    retry: 1,
  });
}
