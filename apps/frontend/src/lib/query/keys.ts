export const qk = {
  me: ["me"] as const,
  catalog: (params: Record<string, unknown>) => ["catalog", params] as const,
  subjects: ["catalog", "subjects"] as const,
  tags: ["catalog", "tags"] as const,
  course: (key: string) => ["course", key] as const,
  reviews: (courseId: string) => ["course", courseId, "reviews"] as const,
  enrollments: ["me", "enrollments"] as const,
  bookmarks: ["me", "bookmarks"] as const,
  myCourses: ["me", "my-courses"] as const,
  chatHistory: (courseId: string) => ["chat", courseId, "history"] as const,
  notifications: ["me", "notifications"] as const,
};
