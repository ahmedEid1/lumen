/* Domain types — kept hand-written for now; regenerate via `pnpm openapi:generate`. */

// S1.11 / ADR-0025: the two-role model. Hand-edited (never `make api-client`,
// DR-5); the OpenAPI↔types drift check is owned by S7. The backend enum stays
// wide (student/instructor) through the Phase-A collapse window, but the UI
// only ever models + assigns the canonical two roles. A stale `/me` carrying a
// legacy role is harmless: every author gate is capability-by-default, and the
// badge path normalises display-side.
export type Role = "user" | "admin";

export interface UserPublic {
  id: string;
  full_name: string;
  avatar_url: string | null;
  bio: string | null;
  role: Role;
}

export interface UserOut extends UserPublic {
  email: string;
  is_active: boolean;
  email_verified_at: string | null;
  created_at: string;
}

export interface SubjectOut {
  id: string;
  title: string;
  slug: string;
  total_courses?: number | null;
}

export interface TagOut {
  id: string;
  name: string;
  slug: string;
}

// S3.7 / ADR-0026: `build_failed` is the terminal state of a self-serve AI
// build that died mid-pipeline (or was cancelled, S3.8). It is NOT listable and
// NOT publishable — the define→build→learn flow reads it to render a clean
// failure surface instead of a half-course. Hand-written (DR-5).
export type CourseStatus = "draft" | "published" | "archived" | "build_failed";
export type Difficulty = "beginner" | "intermediate" | "advanced";
// Hand-written (DR-5: never `make api-client`). Visibility = owner-controlled
// sharing intent; ModerationState = admin/system authority axis (ADR-0026).
export type Visibility = "private" | "public";
export type ModerationState =
  | "none"
  | "pending_review"
  | "approved"
  | "rejected"
  | "delisted";

/**
 * Structured clone provenance (ADR-0028 §Schemas / FR-CLONE-10). Hand-written
 * (DR-5). Serialized from the immutable snapshot columns on a cloned course,
 * kept separate from the editable title/overview so attribution cannot be
 * spoofed. `origin_owner_name` is the read-time value — the server overrides
 * the snapshot with the localized deleted-user label when the origin owner is
 * tombstoned (DR-19). `origin_available` is computed read-time (S4.8): only
 * when it is `true` does the UI render a link to the source.
 */
export interface CourseOrigin {
  origin_course_id: string | null;
  /** From the immutable `origin_title_snapshot` column. */
  origin_title: string | null;
  /** Snapshot name, or the deleted-user label when the owner is tombstoned. */
  origin_owner_name: string | null;
  origin_owner_id: string | null;
  cloned_at: string | null;
  /** Server-computed: origin still live + publicly listed. Gates the link. */
  origin_available: boolean;
}

export interface CourseListItem {
  id: string;
  title: string;
  slug: string;
  overview: string;
  difficulty: Difficulty;
  cover_url: string | null;
  status: CourseStatus;
  /** Read-only sharing intent (ADR-0026). Always present. */
  visibility: Visibility;
  /**
   * Internal moderation churn — REDACTED to `null` for non-owner/non-admin
   * viewers (FR-VIS-21). Only the owner/admin sees the real value.
   */
  moderation_state: ModerationState | null;
  is_featured: boolean;
  published_at: string | null;
  created_at: string;
  owner: UserPublic;
  subject: SubjectOut;
  tags: TagOut[];
  modules_count: number;
  enrollments_count: number;
  avg_rating: number | null;
  /**
   * Clone provenance (ADR-0028 / FR-CLONE-09/10). `origin` is the structured
   * "Based on …" attribution — `null` for a from-scratch course. `is_clone`
   * is the studio "Cloned" badge flag.
   */
  origin: CourseOrigin | null;
  is_clone: boolean;
}

export type LessonType = "text" | "video" | "image" | "file" | "quiz";

/**
 * Shape of `lesson.data` for `type === "text"` lessons. The block
 * editor (Phase E6) writes `blocks`; pre-E6 lessons stored their
 * content in `body_markdown`. We keep both fields typed so the
 * editor / player can resolve whichever exists on the wire — the
 * promotion path is in `@/lib/lesson/blocks#resolveTextLessonDoc`.
 *
 * `blocks` is intentionally typed as `unknown` here rather than
 * importing `BlockDoc` to keep this file dependency-free. The
 * runtime guard (`isBlockDoc`) in `lib/lesson/blocks.ts` enforces
 * the real shape before it reaches the renderer.
 */
export interface TextLessonData {
  blocks?: unknown;
  body_markdown?: string;
  /** Optional alias kept for forward-compat with the rebuild spec wording. */
  body?: string;
}

export interface LessonOut {
  id: string;
  title: string;
  type: LessonType;
  order: number;
  duration_seconds: number | null;
  is_preview: boolean;
  /** Populated by the course-detail endpoint when the viewer is enrolled. */
  completed?: boolean;
  /**
   * Lesson-type-specific payload. Discriminate at the call site
   * using `lesson.type` — e.g. cast to `TextLessonData` when
   * `type === "text"`.
   */
  data: Record<string, unknown>;
}

export interface ModuleOut {
  id: string;
  title: string;
  description: string;
  order: number;
  lessons: LessonOut[];
}

export interface CourseDetail extends CourseListItem {
  modules: ModuleOut[];
  is_enrolled: boolean;
  progress_pct: number;
  /** Derived: the canonical R-C1′ publicly-listed predicate result. */
  is_publicly_listed: boolean;
  /** Owner-only capability hint; `null` for non-owner/non-admin viewers. */
  can_publish_public: boolean | null;
  learning_outcomes: string[];
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface EnrollmentOut {
  id: string;
  course: CourseListItem;
  created_at: string;
  completed_at: string | null;
  certificate_id: string | null;
  progress_pct: number;
}

export interface ReviewOut {
  id: string;
  rating: number;
  body: string;
  created_at: string;
  updated_at: string;
  author: UserPublic;
}

export interface TokenResponse {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  user: UserOut;
}

// ---------- BYOK (S5) — hand-written per DR-5; do NOT `make api-client` ----------

/** One allowlisted provider as returned by GET /api/v1/llm-providers.
 * No base_url, no key material — those are server-internal (DR-17). */
export interface LLMProvider {
  provider: string;
  display_name: string;
  models: string[];
}

export interface LLMProviderRegistry {
  providers: LLMProvider[];
  /** Server's feature_byok_enabled flag — the settings tab gates on this
   * (with the flag off the registry reads empty + false). */
  byok_enabled: boolean;
}

export type LLMValidationStatus =
  | "unvalidated"
  | "valid"
  | "invalid"
  | "error"
  | "needs_attention";

/** Masked credential read shape. NEVER carries the key / enc_* fields. */
export interface LLMCredentialPublic {
  provider: string;
  model: string;
  last4: string;
  enabled: boolean;
  is_active: boolean;
  allow_platform_fallback: boolean;
  last_validated_at: string | null;
  last_validation_status: LLMValidationStatus;
  created_at: string;
}

export interface LLMCredentialValidateResult {
  status: LLMValidationStatus;
  message: string;
}

// ---------- Admin moderation + lifecycle (S6) — hand-written per DR-5 ----------

/**
 * The unified moderation + suspension reason taxonomy (S6.1
 * `moderation_taxonomy.ReasonCode`). Kept in lockstep with the backend
 * `StrEnum` (DR-5: never `make api-client`). The frontend localises each
 * code for the reason picker.
 */
export type ReasonCode =
  | "spam"
  | "abuse"
  | "fraud"
  | "tos_violation"
  | "copyright"
  | "security"
  | "illegal"
  | "csam"
  | "severe_abuse"
  | "other";

/** Reasons that trigger a full quarantine (DR-18-R2): even the owner and
 * enrolled learners lose access. Mirrors `QUARANTINE_REASONS`. */
export const QUARANTINE_REASONS: ReasonCode[] = ["csam", "illegal"];

/** Reasons that hard-remove a course (soft-delete + revoke enrolled access).
 * Superset of the quarantine set plus `severe_abuse`. */
export const HARD_REMOVAL_REASONS: ReasonCode[] = ["csam", "illegal", "severe_abuse"];

/** All reason codes in display order — drives the reason picker. */
export const ALL_REASON_CODES: ReasonCode[] = [
  "spam",
  "abuse",
  "fraud",
  "tos_violation",
  "copyright",
  "security",
  "illegal",
  "csam",
  "severe_abuse",
  "other",
];

/**
 * One row of the admin moderation queue. The backend renders these as
 * admin-viewer `CourseListItem`s plus a `queue_reason` honesty marker (F3):
 * `pending_review` for a course awaiting first approval, or `flagged` for an
 * already-approved-and-still-listed course that accumulated enough user reports
 * to need re-review (R-S11). The UI badge reads this so a flagged-but-public
 * course isn't mislabelled as un-vetted.
 */
export type ModerationQueueReason = "pending_review" | "flagged";

export type ModerationQueueItem = CourseListItem & {
  queue_reason: ModerationQueueReason;
};

/** Admin-viewer course list item (S6.4). Same shape as `CourseListItem`;
 * the admin endpoint surfaces the real `moderation_state`/`visibility`. */
export type CourseAdminOut = CourseListItem;

export type ReportStatus = "open" | "actioned" | "dismissed";

/**
 * Admin report DTO (S6.4 `admin.ReportOut`). Carries reporter PII
 * (FR-MOD-12, admin-only); `note` is the already-sanitized inert text
 * (FR-MOD-13) so it is rendered as plain text, never as markup.
 */
export interface ReportOut {
  id: string;
  course_id: string;
  reporter_id: string;
  reason: string;
  note: string | null;
  status: string;
  created_at: string;
  resolved_at: string | null;
  resolved_by: string | null;
}

/** Resolve action for an open report (S6.4 `ReportResolveRequest`). */
export type ReportResolveAction = "dismiss" | "delist" | "remove";

/**
 * Platform stats (S6.9 `PlatformStatsOut`). The role-derived `instructors`
 * count is replaced by `admins` (`role==admin`) + `authors`
 * (`COUNT(DISTINCT owner_id)` over non-deleted courses).
 */
export interface PlatformStats {
  users: number;
  active_users: number;
  admins: number;
  authors: number;
  courses_total: number;
  courses_published: number;
  courses_listed: number;
  courses_draft: number;
  enrollments: number;
}

/** Admin-managed user row (S6.6/S6.7 `UserAdminOut`). */
export interface UserAdminOut {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

// ---------- S3: goal-intake / define → build (FR-DEFINE) ----------
//
// Hand-written (DR-5: NEVER `make api-client`). Mirrors the backend Pydantic
// DTOs in `app/schemas/learning_brief.py` + the `goal_intake.py` route bodies.
//
// PRIVACY CONTRACT (FR-PRIV-01 / charter decision 2): the raw goal text is the
// learner's input ONLY — it is field-encrypted at rest server-side and NEVER
// returned on any output DTO. `goal_summary` is the non-sensitive paraphrase
// that is safe to surface. There is deliberately no `goal` field on
// `BriefDraft`-as-output or `BriefOut`.

/** Self-assessed learner level (maps 1:1 to course `Difficulty`, DR-4). */
export type BriefLevel = "beginner" | "intermediate" | "advanced";

/**
 * The accumulated, still-mutable structured brief during elicitation. Every
 * field is optional — they fill in across turns (FR-DEFINE-08). Also the shape
 * of the `edits` payload applied once on finalize (FR-DEFINE-03).
 */
export interface BriefDraft {
  goal_summary?: string | null;
  level?: BriefLevel | null;
  prior_knowledge?: string | null;
  time_budget_hours?: number | null;
  sessions_per_week?: number | null;
  desired_outcomes?: string[];
  format_prefs?: Record<string, boolean>;
  language?: string | null;
  suggested_subject?: string | null;
}

/**
 * The assistant's reply + the running brief + bounded-turn bookkeeping
 * (`GoalTurnResponse`). `turns_remaining` reaching 0 is the turn-cap signal the
 * UI surfaces (R-M10); `converged` unlocks the review→build step.
 */
export interface GoalTurnResponse {
  session_id: string;
  assistant_message: string;
  accumulated_brief: BriefDraft;
  turns_used: number;
  turns_remaining: number;
  converged: boolean;
}

/**
 * The finalized, immutable brief — STRUCTURED FIELDS ONLY (FR-PRIV-01). Omits
 * the raw goal text and the `source_goal_enc` ciphertext by construction.
 */
export interface BriefOut {
  id: string;
  level: BriefLevel | string | null;
  time_budget_hours: number | null;
  sessions_per_week: number | null;
  prior_knowledge: string | null;
  desired_outcomes: string[];
  goal_summary: string | null;
  suggested_subject: string | null;
  language: string | null;
  finalized_at: string | null;
}

/**
 * The built (or idempotently replayed) PRIVATE draft course + its
 * reasoning-trace id (`DraftFromBriefResponse`). The slug is the deep-link key
 * into the owner self-learn surface (`/learn/[slug]`, FR-LEARN-01).
 */
export interface DraftFromBriefResponse {
  course_id: string;
  slug: string;
  module_count: number;
  lesson_count: number;
  draft_id: string;
  revisions_used: number;
}

/**
 * The in-flight / built course a finalized brief produced
 * (`GET /me/briefs/{id}/course`, Gate-B F1). The define UI polls this while
 * `phase === "building"` to obtain the cancel target (`course_id`) and detect a
 * terminal state (`status === "build_failed"` = failed/cancelled) BEFORE the
 * synchronous build endpoint returns — a 404 means the build shell hasn't
 * materialized yet ("still spinning up").
 */
export interface BriefCourseStatus {
  course_id: string;
  status: string;
}
