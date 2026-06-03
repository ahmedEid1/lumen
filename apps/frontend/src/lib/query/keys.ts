export const qk = {
  me: ["me"] as const,
  catalog: (params: Record<string, unknown>) => ["catalog", params] as const,
  subjects: ["catalog", "subjects"] as const,
  tags: ["catalog", "tags"] as const,
  course: (key: string) => ["course", key] as const,
  reviews: (courseId: string) => ["course", courseId, "reviews"] as const,
  enrollments: ["me", "enrollments"] as const,
  myCourses: ["me", "my-courses"] as const,
  notifications: ["me", "notifications"] as const,
  reviewsQueue: ["me", "reviews", "queue"] as const,
  reviewsStats: ["me", "reviews", "stats"] as const,
  mastery: ["me", "mastery"] as const,
  runtimeFlags: ["runtime-flags"] as const,
  demoQuestions: (courseSlug?: string) =>
    ["demo-questions", courseSlug ?? "all"] as const,
  evalPublic: ["eval-public"] as const,
  // S5 (BYOK)
  llmProviders: ["llm-providers"] as const,
  llmCredentials: ["me", "llm-credentials"] as const,
  // S2.12 — moderation surfaces. ``catalogRoot`` is the prefix used to
  // invalidate every catalog/subjects/tags query in one call on a share/
  // approve/delist mutation.
  catalogRoot: ["catalog"] as const,
  moderationQueue: ["admin", "moderation", "queue"] as const,
  courseModeration: (id: string) => ["course", id, "moderation"] as const,
};
