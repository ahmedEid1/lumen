import { api } from "@/lib/api/client";
import type {
  CourseDetail,
  CourseListItem,
  EnrollmentOut,
  LessonOut,
  ModuleOut,
  Page,
  ReviewOut,
  SubjectOut,
  TagOut,
  TokenResponse,
  UserOut,
} from "@/lib/api/types";

// ---------- Auth ----------
export const Auth = {
  register: (input: { email: string; password: string; full_name: string }) =>
    api<UserOut>("/api/v1/auth/register", { method: "POST", body: input }),
  login: (input: { email: string; password: string }) =>
    api<TokenResponse>("/api/v1/auth/login", { method: "POST", body: input }),
  refresh: () => api<TokenResponse>("/api/v1/auth/refresh", { method: "POST" }),
  logout: () => api<{ ok: true }>("/api/v1/auth/logout", { method: "POST" }),
  me: (token?: string) => api<UserOut>("/api/v1/auth/me", { token }),
};

// ---------- Catalog ----------
export const Catalog = {
  subjects: () => api<SubjectOut[]>("/api/v1/subjects"),
  tags: () => api<TagOut[]>("/api/v1/tags"),
  courses: (params: {
    q?: string;
    subject?: string;
    tag?: string;
    difficulty?: string;
    sort?: string;
    page?: number;
    page_size?: number;
  } = {}) => {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
    }
    const suffix = qs.toString() ? `?${qs}` : "";
    return api<Page<CourseListItem>>(`/api/v1/courses${suffix}`);
  },
};

// ---------- Courses ----------
export const Courses = {
  get: (key: string) => api<CourseDetail>(`/api/v1/courses/${encodeURIComponent(key)}`),
  mine: (token?: string) => api<CourseListItem[]>("/api/v1/courses/mine", { token }),
  create: (
    input: {
      title: string;
      subject_id: string;
      overview?: string;
      difficulty?: string;
      cover_url?: string;
      tag_ids?: string[];
    },
    token?: string,
  ) => api<CourseListItem>("/api/v1/courses", { method: "POST", body: input, token }),
  patch: (id: string, input: Record<string, unknown>, token?: string) =>
    api<CourseDetail>(`/api/v1/courses/${id}`, { method: "PATCH", body: input, token }),
  remove: (id: string, token?: string) =>
    api<{ ok: true }>(`/api/v1/courses/${id}`, { method: "DELETE", token }),

  createModule: (courseId: string, input: { title: string; description?: string }, token?: string) =>
    api<ModuleOut>(`/api/v1/courses/${courseId}/modules`, { method: "POST", body: input, token }),
  reorderModules: (courseId: string, order: Record<string, number>, token?: string) =>
    api<{ ok: true }>(`/api/v1/courses/${courseId}/modules/order`, {
      method: "POST",
      body: { order },
      token,
    }),
  patchModule: (
    moduleId: string,
    input: { title?: string; description?: string },
    token?: string,
  ) =>
    api<ModuleOut>(`/api/v1/courses/modules/${moduleId}`, {
      method: "PATCH",
      body: input,
      token,
    }),
  deleteModule: (moduleId: string, token?: string) =>
    api<{ ok: true }>(`/api/v1/courses/modules/${moduleId}`, { method: "DELETE", token }),

  createLesson: (moduleId: string, input: Record<string, unknown>, token?: string) =>
    api(`/api/v1/courses/modules/${moduleId}/lessons`, { method: "POST", body: input, token }),
  patchLesson: (lessonId: string, input: Record<string, unknown>, token?: string) =>
    api(`/api/v1/courses/lessons/${lessonId}`, { method: "PATCH", body: input, token }),
  deleteLesson: (lessonId: string, token?: string) =>
    api<{ ok: true }>(`/api/v1/courses/lessons/${lessonId}`, { method: "DELETE", token }),
  reorderLessons: (moduleId: string, order: Record<string, number>, token?: string) =>
    api<{ ok: true }>(`/api/v1/courses/modules/${moduleId}/lessons/order`, {
      method: "POST",
      body: { order },
      token,
    }),

  analytics: (courseId: string, token?: string) =>
    api<{
      course_id: string;
      enrollments: number;
      completions: number;
      completion_rate: number;
      avg_rating: number | null;
      rating_count: number;
      avg_progress_pct: number;
      enrollments_last_7d: number;
      enrollments_last_30d: number;
    }>(`/api/v1/courses/${courseId}/analytics`, { token }),

  getLesson: (lessonId: string, token?: string) =>
    api<LessonOut>(`/api/v1/courses/lessons/${lessonId}`, { token }),

  cohort: (courseId: string, token?: string) =>
    api<
      Array<{
        user_id: string;
        full_name: string;
        avatar_url: string | null;
        enrolled_at: string;
        completed_at: string | null;
        progress_pct: number;
        certificate_id: string | null;
      }>
    >(`/api/v1/courses/${courseId}/students`, { token }),
};

// ---------- Enrollments ----------
export const Me = {
  enrollments: (token?: string) => api<EnrollmentOut[]>("/api/v1/me/enrollments", { token }),
  enroll: (courseId: string, token?: string) =>
    api<EnrollmentOut>(`/api/v1/me/enrollments/${courseId}`, { method: "POST", token }),
  unenroll: (courseId: string, token?: string) =>
    api<{ ok: true }>(`/api/v1/me/enrollments/${courseId}`, { method: "DELETE", token }),
  markLesson: (lessonId: string, completed: boolean, token?: string) =>
    api(`/api/v1/me/progress/lessons/${lessonId}`, {
      method: "POST",
      body: { completed },
      token,
    }),
  notifications: (token?: string) => api("/api/v1/me/notifications", { token }),
  /** Phase E7 — bundled mastery dashboard (weak spots + per-course
   *  rollups). Fetched as a single round-trip so the surface paints
   *  both sections on one loading state. */
  mastery: (token?: string) =>
    api<MasteryResponse>("/api/v1/me/mastery", { token }),
  markNotificationRead: (id: string, token?: string) =>
    api<{ ok: true }>(`/api/v1/me/notifications/${id}/read`, { method: "POST", token }),
  markAllNotificationsRead: (token?: string) =>
    api<{ ok: true; marked_read: number }>("/api/v1/me/notifications/read-all", {
      method: "POST",
      token,
    }),
  // Phase D4 — per-kind notification dispatch prefs.
  notificationPrefs: {
    get: (token?: string) =>
      api<NotificationPrefsResponse>("/api/v1/me/notifications/prefs", { token }),
    update: (prefs: Record<string, NotificationDispatch>, token?: string) =>
      api<NotificationPrefsResponse>("/api/v1/me/notifications/prefs", {
        method: "PUT",
        body: { prefs },
        token,
      }),
  },
};

// ---------- Mastery dashboard (Phase E7) ----------

/** Stable signal codes attached to a weak-spot row. The frontend
 * localises each code and picks a Badge variant from it. */
export type MasterySignal =
  | "quiz_failed"
  | "card_overdue"
  | "quiz_low"
  | "tutor_repeat";

/** Slimmed lesson + course context attached to a weak-spot row. */
export interface MasteryWeakSpotLesson {
  id: string;
  title: string;
  course_id: string;
  course_slug: string;
  course_title: string;
}

/** One actionable row on the mastery dashboard. */
export interface MasteryWeakSpot {
  lesson: MasteryWeakSpotLesson;
  signals: MasterySignal[];
  /** Open-ended details map: ``quiz_score``, ``overdue_days``,
   * ``tutor_count``. Always strings so JSON shape stays uniform. */
  signal_details: Record<string, string>;
  /** When the lesson has an FSRS card currently due, the
   *  "Review now" CTA deep-links into the spaced-repetition queue. */
  review_card_id: string | null;
}

/** Per-enrolled-course rollup row. */
export interface MasteryCourse {
  course_id: string;
  slug: string;
  title: string;
  mastery_pct: number;
  completion_pct: number;
}

/** Bundled mastery dashboard payload. */
export interface MasteryResponse {
  weak_spots: MasteryWeakSpot[];
  courses: MasteryCourse[];
}

// Phase D4 — keep this in sync with backend NotificationKind /
// NotificationDispatch enums.
export type NotificationKind =
  | "enrolled"
  | "lesson_available"
  | "certificate_ready"
  | "review_received"
  | "chat_mention"
  | "security"
  | "discussion_reply";

export type NotificationDispatch =
  | "off"
  | "in_app"
  | "email_immediate"
  | "digest_daily";

export interface NotificationPrefsResponse {
  prefs: Record<NotificationKind, NotificationDispatch>;
}

// ---------- Studio content ingest (Phase E3) ----------

export type IngestSource = "youtube" | "notion" | "google_docs" | "unknown";

export interface IngestLessonDraft {
  title: string;
  type: "text";
  body: string;
  anchor: string | null;
}

export interface IngestModuleDraft {
  title: string;
  lessons: IngestLessonDraft[];
}

export interface IngestPayload {
  title: string;
  source_url: string;
  source: IngestSource;
  modules: IngestModuleDraft[];
}

export interface IngestCommitResponse {
  course_id: string;
  modules: number;
  lessons: number;
}

export const Ingest = {
  detect: (url: string, token?: string) =>
    api<{ source: IngestSource }>(`/api/v1/studio/ingest/detect`, {
      method: "POST",
      body: { url },
      token,
    }),
  preview: (url: string, token?: string) =>
    api<IngestPayload>(`/api/v1/studio/ingest/preview`, {
      method: "POST",
      body: { url },
      token,
    }),
  commit: (input: { course_id: string; payload: IngestPayload }, token?: string) =>
    api<IngestCommitResponse>(`/api/v1/studio/ingest/commit`, {
      method: "POST",
      body: input,
      token,
    }),
};

// ---------- AI authoring (Phase E2) ----------

export interface OutlineLesson {
  title: string;
  type: "text" | "quiz";
}

export interface OutlineModule {
  title: string;
  lessons: OutlineLesson[];
}

export interface CourseOutline {
  title: string;
  overview: string;
  modules: OutlineModule[];
}

export interface AIQuizQuestion {
  id: string;
  prompt: string;
  kind: "single" | "multiple" | "short";
  choices: { id: string; text: string }[];
  answer_keys: string[];
}

export interface CommittedLesson {
  id: string;
  title: string;
  type: string;
  order: number;
}

export interface CommittedModule {
  id: string;
  title: string;
  order: number;
  lessons: CommittedLesson[];
}

export interface CommitOutlineResponse {
  course_id: string;
  modules: CommittedModule[];
}

export const AI = {
  outline: (input: { brief: string; target_modules?: number }, token?: string) =>
    api<CourseOutline>("/api/v1/studio/ai/outline", {
      method: "POST",
      body: input,
      token,
    }),
  lessonBody: (
    input: { lesson_title: string; course_context?: string },
    token?: string,
  ) =>
    api<{ blocks: Record<string, unknown> }>("/api/v1/studio/ai/lesson-body", {
      method: "POST",
      body: input,
      token,
    }),
  quiz: (
    input: { lesson_title: string; course_context?: string; n?: number },
    token?: string,
  ) =>
    api<{ questions: AIQuizQuestion[] }>("/api/v1/studio/ai/quiz", {
      method: "POST",
      body: input,
      token,
    }),
  commitOutline: (
    input: { course_id: string; outline: CourseOutline },
    token?: string,
  ) =>
    api<CommitOutlineResponse>("/api/v1/studio/ai/commit-outline", {
      method: "POST",
      body: input,
      token,
    }),
};

// ---------- Reviews ----------
export const Reviews = {
  list: (courseId: string) => api<ReviewOut[]>(`/api/v1/courses/${courseId}/reviews`),
  upsert: (courseId: string, input: { rating: number; body: string }, token?: string) =>
    api<ReviewOut>(`/api/v1/courses/${courseId}/reviews`, {
      method: "PUT",
      body: input,
      token,
    }),
  remove: (courseId: string, token?: string) =>
    api<{ ok: true }>(`/api/v1/courses/${courseId}/reviews`, { method: "DELETE", token }),
};

// ---------- Reviews queue (FSRS-6, Phase E4) ----------

export type ReviewCardState = "new" | "learning" | "review" | "relearning";

export interface ReviewCardLesson {
  id: string;
  title: string;
  course_id: string;
  course_title: string;
  course_slug: string;
}

export interface ReviewCardOut {
  id: string;
  state: ReviewCardState;
  stability: number;
  difficulty: number;
  due_at: string;
  last_reviewed_at: string | null;
  total_reviews: number;
  lesson: ReviewCardLesson;
}

export interface ReviewQueueResponse {
  items: ReviewCardOut[];
}

export interface ReviewStatsResponse {
  due: number;
  learning: number;
  review: number;
  next_7_days: number;
}

export type ReviewRating = "again" | "hard" | "good" | "easy";

export const ReviewsQueue = {
  queue: (token?: string, limit = 20) =>
    api<ReviewQueueResponse>(`/api/v1/me/reviews/queue?limit=${limit}`, { token }),
  stats: (token?: string) =>
    api<ReviewStatsResponse>("/api/v1/me/reviews/stats", { token }),
  grade: (cardId: string, rating: ReviewRating, token?: string) =>
    api<ReviewCardOut>(`/api/v1/me/reviews/${cardId}/grade`, {
      method: "POST",
      body: { rating },
      token,
    }),
};

// ---------- Tutor (course-scoped RAG, Phase E1) ----------

/** One citation pill rendered under an assistant message. */
export interface TutorCitation {
  lesson_id: string;
  lesson_title: string;
  chunk_excerpt: string;
}

/** One turn in a tutor conversation. */
export interface TutorMessageOut {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: TutorCitation[];
  created_at: string;
}

/** Conversation list row in the "my recent threads" panel. */
export interface TutorConversationSummary {
  id: string;
  course_id: string;
  created_at: string;
  last_message_at: string;
  last_message_preview: string;
  message_count: number;
}

/** Full conversation detail with its message history. */
export interface TutorConversationDetail {
  id: string;
  course_id: string;
  created_at: string;
  last_message_at: string;
  messages: TutorMessageOut[];
}

/** One sub-agent dispatch as rendered in the agent-reasoning panel (Phase I2). */
export interface TutorToolCallTrace {
  tool_name: string;
  args: Record<string, unknown>;
  rationale: string;
  result_summary: string;
  result_details: Record<string, unknown>;
}

/** Both turns returned by a single POST /messages call. */
export interface TutorPostResponse {
  user_message: TutorMessageOut;
  assistant_message: TutorMessageOut;
  refused: boolean;
  /** Phase I2: 0-5 self-reported by the planner / re-planner. */
  confidence?: number;
  /** Phase I2: per-turn tool-call log for the agent-reasoning panel. */
  agent_trace?: TutorToolCallTrace[];
}

export const Tutor = {
  startConversation: (courseId: string, token?: string) =>
    api<TutorConversationDetail>(
      `/api/v1/courses/${encodeURIComponent(courseId)}/tutor/conversations`,
      { method: "POST", token },
    ),
  listConversations: (
    courseId: string,
    params: { page?: number; page_size?: number } = {},
    token?: string,
  ) => {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null) qs.set(k, String(v));
    }
    const suffix = qs.toString() ? `?${qs}` : "";
    return api<Page<TutorConversationSummary>>(
      `/api/v1/courses/${encodeURIComponent(courseId)}/tutor/conversations${suffix}`,
      { token },
    );
  },
  getConversation: (conversationId: string, token?: string) =>
    api<TutorConversationDetail>(
      `/api/v1/tutor/conversations/${encodeURIComponent(conversationId)}`,
      { token },
    ),
  postMessage: (conversationId: string, content: string, token?: string) =>
    api<TutorPostResponse>(
      `/api/v1/tutor/conversations/${encodeURIComponent(conversationId)}/messages`,
      { method: "POST", body: { content }, token },
    ),
};

