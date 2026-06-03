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

export interface CourseListItem {
  id: string;
  title: string;
  slug: string;
  overview: string;
  difficulty: Difficulty;
  cover_url: string | null;
  status: CourseStatus;
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
