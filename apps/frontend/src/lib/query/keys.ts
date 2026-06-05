export const qk = {
  me: ["me"] as const,
  catalog: (params: Record<string, unknown>) => ["catalog", params] as const,
  subjects: ["catalog", "subjects"] as const,
  tags: ["catalog", "tags"] as const,
  course: (key: string) => ["course", key] as const,
  reviews: (courseId: string) => ["course", courseId, "reviews"] as const,
  // S4.11 (ADR-0028) — clone surfaces. `clone` namespaces the in-flight clone
  // mutation for a source; `courseClones` is the origin-owner "who cloned this"
  // list (FR-CLONE-24, deferred view). On clone success the mutation invalidates
  // `myCourses` + `enrollments` (the cloner is auto-enrolled).
  clone: (key: string) => ["course", key, "clone"] as const,
  courseClones: (key: string) => ["course", key, "clones"] as const,
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
  // S6.11 — admin report queue. ``reports`` is the base; filters append.
  reports: ["admin", "reports"] as const,
  adminUsers: ["admin", "users"] as const,
  adminStats: ["admin", "stats"] as const,
  // S3.11 — define→build→learn. `goalSession` namespaces an in-flight
  // goal-intake conversation by its session id; `brief` is the finalized,
  // immutable brief. The build-progress surface reuses the existing
  // `["draft-trace", courseId]` key (CourseDraftTrace) for the trace timeline
  // and `qk.course(slug)` for the build-status poll.
  goalSession: (id: string) => ["define", "goal", id] as const,
  brief: (id: string) => ["define", "brief", id] as const,
};
