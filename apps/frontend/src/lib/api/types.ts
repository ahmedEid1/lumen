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

export type CourseStatus = "draft" | "published" | "archived";
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
