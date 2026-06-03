/* Domain types — kept hand-written for now; regenerate via `pnpm openapi:generate`. */

export type Role = "student" | "instructor" | "admin";

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
