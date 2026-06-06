import { api } from "@/lib/api/client";
import type {
  BriefCourseStatus,
  BriefDraft,
  BriefOut,
  CourseAdminOut,
  CourseDetail,
  CourseListItem,
  DraftFromBriefResponse,
  EnrollmentOut,
  GoalTurnResponse,
  LessonOut,
  LLMCredentialPublic,
  LLMCredentialValidateResult,
  LLMProviderRegistry,
  ModerationQueueItem,
  ModuleOut,
  Page,
  PlatformStats,
  ReasonCode,
  ReportOut,
  ReportResolveAction,
  ReviewOut,
  SubjectOut,
  TagOut,
  TokenResponse,
  UserAdminOut,
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

  // Two-control lifecycle + share model (S2.11 / ADR-0026). publish/unpublish
  // are the lifecycle axis; share/unshare/resubmit are the (flag-gated)
  // sharing axis — while FEATURE_PRIVATE_PUBLISH_ENABLED is off the share
  // endpoints 404.
  publish: (id: string, token?: string) =>
    api<CourseDetail>(`/api/v1/courses/${id}/publish`, { method: "POST", token }),
  unpublish: (id: string, token?: string) =>
    api<CourseDetail>(`/api/v1/courses/${id}/unpublish`, { method: "POST", token }),
  archive: (id: string, token?: string) =>
    api<CourseDetail>(`/api/v1/courses/${id}/archive`, { method: "POST", token }),
  restore: (id: string, token?: string) =>
    api<CourseDetail>(`/api/v1/courses/${id}/restore`, { method: "POST", token }),
  share: (id: string, token?: string) =>
    api<CourseDetail>(`/api/v1/courses/${id}/share`, { method: "POST", body: {}, token }),
  unshare: (id: string, token?: string) =>
    api<CourseDetail>(`/api/v1/courses/${id}/unshare`, { method: "POST", body: {}, token }),
  resubmit: (id: string, token?: string) =>
    api<CourseDetail>(`/api/v1/courses/${id}/resubmit`, { method: "POST", body: {}, token }),
  moderationQueue: (token?: string) =>
    api<CourseListItem[]>("/api/v1/admin/courses/moderation-queue", { token }),

  // S4.11 (ADR-0028 §API) — clone a publicly-listed course into a fresh
  // private draft. Returns the new CourseListItem (201). Hand-written per DR-5.
  // While CLONE_ENABLED is off server-side the endpoint existence-hides (404),
  // surfaced as a toast — the same flag pattern as share/unshare.
  clone: ({ key, token }: { key: string; token?: string }) =>
    api<CourseListItem>(`/api/v1/courses/${encodeURIComponent(key)}/clone`, {
      method: "POST",
      token,
    }),

  // S6.3 — any authenticated user files a report against a publicly-listed
  // course. `note` is sanitized server-side (FR-MOD-13).
  report: (
    id: string,
    body: { reason: ReasonCode; note?: string | null },
    token?: string,
  ) =>
    api<{ ok: true }>(`/api/v1/courses/${encodeURIComponent(id)}/report`, {
      method: "POST",
      body,
      token,
    }),

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

// ---------- Admin moderation + user management (S6) ----------

/** Body for the moderation action endpoints (S6.4 `ModerationActionRequest`). */
export interface ModerationActionBody {
  reason?: ReasonCode | null;
  note?: string | null;
}

/** The admin-authority moderation + user-lifecycle surface. Every method
 * here routes through `RequireAdmin` on the backend (FR-ADMIN-08: the UI gate
 * is defense-in-depth, the backend gate is authoritative). */
export const Admin = {
  // -- Moderation queue + report queue
  moderationQueue: (token?: string) =>
    api<ModerationQueueItem[]>("/api/v1/admin/courses/moderation-queue", { token }),
  reports: (
    params: { status?: string; reason?: string; course_id?: string; cursor?: string } = {},
    token?: string,
  ) => {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
    }
    const suffix = qs.toString() ? `?${qs}` : "";
    return api<ReportOut[]>(`/api/v1/admin/reports${suffix}`, { token });
  },

  // -- Course moderation transitions (S6.2/S6.4)
  approveCourse: (id: string, body: ModerationActionBody = {}, token?: string) =>
    api<CourseAdminOut>(`/api/v1/admin/courses/${id}/approve`, {
      method: "POST",
      body,
      token,
    }),
  rejectCourse: (id: string, body: ModerationActionBody = {}, token?: string) =>
    api<CourseAdminOut>(`/api/v1/admin/courses/${id}/reject`, {
      method: "POST",
      body,
      token,
    }),
  delistCourse: (id: string, body: ModerationActionBody = {}, token?: string) =>
    api<CourseAdminOut>(`/api/v1/admin/courses/${id}/delist`, {
      method: "POST",
      body,
      token,
    }),
  relistCourse: (id: string, body: ModerationActionBody = {}, token?: string) =>
    api<CourseAdminOut>(`/api/v1/admin/courses/${id}/relist`, {
      method: "POST",
      body,
      token,
    }),
  // `reason` is required (the backend 422s without it).
  removeCourse: (
    id: string,
    body: { reason: ReasonCode; note?: string | null },
    token?: string,
  ) =>
    api<CourseAdminOut>(`/api/v1/admin/courses/${id}/remove`, {
      method: "POST",
      body,
      token,
    }),

  // -- Report resolution (S6.4): performs the linked moderation action
  // atomically in one transaction.
  resolveReport: (
    id: string,
    body: { action: ReportResolveAction; reason?: ReasonCode | null; note?: string | null },
    token?: string,
  ) =>
    api<ReportOut>(`/api/v1/admin/reports/${id}/resolve`, {
      method: "POST",
      body,
      token,
    }),

  // -- User management (S6.6/S6.7)
  // Returns the repo-standard offset+page envelope `Page<UserAdminOut>`,
  // mirroring `GET /api/v1/admin/users` in backend admin.py (`response_model=
  // Page[UserAdminOut]`). The earlier bare-`UserAdminOut[]` + `limit` shape
  // drifted from admin.py and painted empty rows on /admin/users (W11 F6).
  users: (params: { q?: string; page?: number; page_size?: number } = {}, token?: string) => {
    const qs = new URLSearchParams();
    if (params.q) qs.set("q", params.q);
    if (params.page !== undefined) qs.set("page", String(params.page));
    qs.set("page_size", String(params.page_size ?? 50));
    return api<Page<UserAdminOut>>(`/api/v1/admin/users?${qs}`, { token });
  },
  setAdmin: (id: string, isAdmin: boolean, token?: string) =>
    api<UserAdminOut>(`/api/v1/admin/users/${id}/admin`, {
      method: "PATCH",
      body: { is_admin: isAdmin },
      token,
    }),
  suspendUser: (
    id: string,
    body: { reason: ReasonCode; note?: string | null },
    token?: string,
  ) =>
    api<UserAdminOut>(`/api/v1/admin/users/${id}/suspend`, {
      method: "PATCH",
      body,
      token,
    }),
  reinstateUser: (id: string, token?: string) =>
    api<UserAdminOut>(`/api/v1/admin/users/${id}/reinstate`, {
      method: "PATCH",
      body: {},
      token,
    }),

  // -- Platform stats (S6.9)
  stats: (token?: string) => api<PlatformStats>("/api/v1/admin/stats", { token }),
};

// ---------- Users (self-service account) ----------
export const Users = {
  // S6.8 — anonymize-in-place account deletion. Requires the current
  // password; on success the caller clears the query cache + hard-redirects.
  deleteMe: (password: string, token?: string) =>
    api<{ ok: true }>("/api/v1/users/me", {
      method: "DELETE",
      body: { password },
      token,
    }),
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

// ---------- BYOK (S5) ----------

/** Read-only allowlisted provider+model registry (no base_url/keys). */
export const LLMProviders = {
  list: (token?: string) => api<LLMProviderRegistry>("/api/v1/llm-providers", { token }),
};

/** Per-user BYOK credential CRUD + validate. The api_key is write-only;
 * reads are always masked (LLMCredentialPublic carries last4 + status). */
export const LLMCredentials = {
  list: (token?: string) =>
    api<LLMCredentialPublic[]>("/api/v1/me/llm-credentials", { token }),
  upsert: (
    provider: string,
    body: { model: string; api_key: string; allow_platform_fallback?: boolean },
    token?: string,
  ) =>
    api<LLMCredentialPublic>(`/api/v1/me/llm-credentials/${provider}`, {
      method: "PUT",
      body,
      token,
    }),
  patch: (
    provider: string,
    body: { enabled?: boolean; is_active?: boolean; allow_platform_fallback?: boolean },
    token?: string,
  ) =>
    api<LLMCredentialPublic>(`/api/v1/me/llm-credentials/${provider}`, {
      method: "PATCH",
      body,
      token,
    }),
  remove: (provider: string, token?: string) =>
    api<{ ok: true }>(`/api/v1/me/llm-credentials/${provider}`, {
      method: "DELETE",
      token,
    }),
  validate: (provider: string, token?: string) =>
    api<LLMCredentialValidateResult>(`/api/v1/me/llm-credentials/${provider}/validate`, {
      method: "POST",
      token,
    }),
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

// ---------- I3: self-critique authoring loop ----------

export interface CriticScoresOut {
  coverage: number;
  learning_arc: number;
  scope: number;
  mean: number;
}

export interface DraftCourseResponse {
  course_id: string;
  slug: string;
  module_count: number;
  lesson_count: number;
  final_score: CriticScoresOut;
  final_rationale: string;
  draft_id: string;
  revisions_used: number;
}

export interface DraftTraceStep {
  id: string;
  draft_id: string;
  course_id: string | null;
  step:
    | "researcher"
    | "outliner"
    | "critic"
    | "reviser"
    | "lesson_drafter"
    | "final_critic"
    | string;
  step_index: number;
  status: "ok" | "error" | string;
  duration_ms: number;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface DraftTraceResponse {
  course_id: string;
  draft_id: string | null;
  steps: DraftTraceStep[];
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
  draftCourse: (
    input: { brief: string; subject_slug: string },
    token?: string,
  ) =>
    api<DraftCourseResponse>("/api/v1/studio/ai/draft-course", {
      method: "POST",
      body: input,
      token,
    }),
  draftTrace: (courseId: string, token?: string) =>
    api<DraftTraceResponse>(
      `/api/v1/studio/drafts/${encodeURIComponent(courseId)}/trace`,
      { token },
    ),
};

// ---------- S3: goal-intake → define → build (FR-DEFINE) ----------
//
// The learner-author entry (NOT `/studio`). `AI.draftCourse` above hits the
// instructor `/studio/ai/draft-course` path and was a dead binding; the live
// self-serve learner build is `Define.draftFromBrief` → `POST /ai/courses/draft`
// (FR-DEFINE-05), which takes a finalized brief id rather than free-text. The
// goal-intake conversation (start/turn/finalize) is bounded (6 turns, R-M10) and
// metered BYOK-eligible server-side (ADR-0027 §4 / DR-8).
export const Define = {
  /** Open a bounded goal-intake conversation with a fuzzy goal (the ONLY
   *  raw-goal input site; encrypted at rest server-side, FR-PRIV-01). */
  startGoal: (goal: string, token?: string) =>
    api<GoalTurnResponse>("/api/v1/ai/goal/start", {
      method: "POST",
      body: { goal },
      token,
    }),
  /** Advance the conversation by one learner reply (FR-DEFINE-02/08). At the
   *  cap the server returns 429 `define.turn_cap` (no LLM call). */
  takeTurn: (sessionId: string, message: string, token?: string) =>
    api<GoalTurnResponse>(
      `/api/v1/ai/goal/${encodeURIComponent(sessionId)}/turn`,
      { method: "POST", body: { message }, token },
    ),
  /** Freeze the brief into an immutable `BriefOut`, applying optional last-mile
   *  `edits` once (FR-DEFINE-03). A second finalize → 422. */
  finalize: (sessionId: string, edits?: BriefDraft, token?: string) =>
    api<BriefOut>(
      `/api/v1/ai/goal/${encodeURIComponent(sessionId)}/finalize`,
      { method: "POST", body: { edits: edits ?? null }, token },
    ),
  /** Build a PRIVATE draft course from a finalized brief (FR-DEFINE-05/11). The
   *  canonical learner build entry; idempotent on the brief id. */
  draftFromBrief: (briefId: string, token?: string) =>
    api<DraftFromBriefResponse>("/api/v1/ai/courses/draft", {
      method: "POST",
      body: { brief_id: briefId },
      token,
    }),
  /** Cancel an in-flight / abandoned build (DR-1a / FR-DEFINE-14a). Owner-scoped
   *  (404 existence-hide for non-owner); flips the course to `build_failed`. */
  cancelBuild: (courseId: string, token?: string) =>
    api<{ ok: true }>(
      `/api/v1/me/courses/${encodeURIComponent(courseId)}/cancel-build`,
      { method: "POST", token },
    ),
  /** The in-flight/built course a finalized brief produced (Gate-B F1). Polled
   *  while building to obtain the cancel target + terminal state before the
   *  synchronous build endpoint returns. 404 = shell not materialized yet. */
  briefCourse: (briefId: string, token?: string) =>
    api<BriefCourseStatus>(
      `/api/v1/me/briefs/${encodeURIComponent(briefId)}/course`,
      { token },
    ),
};

// ---------- Learner + instructor agent traces (Phase I4) ----------
//
// Two surfaces consume these endpoints: the per-turn tutor
// drill-down at /dashboard/tutor/{cid}/turn/{mid} and the
// instructor replay at /studio/draft/{cid}/replay.

export interface TraceLLMCallSummary {
  call_id: string;
  feature: string;
  provider: string;
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: string;
  latency_ms: number;
  status: string;
  created_at: string;
}

export interface TraceStep {
  trace_id: string;
  parent_trace_id: string | null;
  parent_call_id: string | null;
  step: string;
  step_index: number;
  payload: Record<string, unknown>;
  duration_ms: number;
  status: string;
  created_at: string;
}

export interface TraceRetrievalAudit {
  audit_id: string;
  feature: string;
  query: string;
  course_id: string | null;
  chunks: Array<Record<string, unknown>>;
  top_score: number | null;
  created_at: string;
}

export interface TutorTurnTraceResponse {
  message_id: string;
  conversation_id: string;
  course_id: string;
  feature: string;
  llm_call: TraceLLMCallSummary | null;
  agent_traces: TraceStep[];
  retrieval_audits: TraceRetrievalAudit[];
  total_cost_usd: string;
  total_latency_ms: number;
  total_prompt_tokens: number;
  total_completion_tokens: number;
  confidence: number;
  created_at: string;
}

export interface DraftReplayStep {
  id: string;
  draft_id: string;
  course_id: string | null;
  step: string;
  step_index: number;
  status: string;
  duration_ms: number;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface DraftReplayResponse {
  course_id: string;
  draft_id: string | null;
  steps: DraftReplayStep[];
  step_count: number;
  total_duration_ms: number;
}

export const Traces = {
  tutorTurn: (
    conversationId: string,
    messageId: string,
    token?: string,
  ) =>
    api<TutorTurnTraceResponse>(
      `/api/v1/me/tutor/conversations/${encodeURIComponent(
        conversationId,
      )}/turns/${encodeURIComponent(messageId)}/trace`,
      { token },
    ),
  draftReplay: (courseId: string, token?: string) =>
    api<DraftReplayResponse>(
      `/api/v1/me/studio/drafts/${encodeURIComponent(courseId)}/replay`,
      { token },
    ),
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

// ---------- Runtime flags (L20.5) ----------

export interface RuntimeFlags {
  tutor_streaming: boolean;
}

export const RuntimeFlagsApi = {
  get: () => api<RuntimeFlags>("/api/v1/runtime-flags"),
};

// ---------- Demo question library (L20.6) ----------

export type DemoQuestionCategory =
  | "retriever-only"
  | "retriever-code-runner"
  | "retriever-web-searcher"
  | "refusal"
  | "multi-hop";

export interface DemoQuestion {
  id: string;
  category: DemoQuestionCategory;
  prompt: string;
  expected_tools: string[];
  course_slug: string;
  canonical: boolean;
}

export interface DemoQuestionLibrary {
  version: string;
  canonical_id: string;
  questions: DemoQuestion[];
}

export const DemoQuestionsApi = {
  list: (courseSlug?: string) => {
    const qs = courseSlug
      ? `?course_slug=${encodeURIComponent(courseSlug)}`
      : "";
    return api<DemoQuestionLibrary>(`/api/v1/demo-questions${qs}`);
  },
};

