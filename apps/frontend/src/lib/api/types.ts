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

export interface LessonOut {
  id: string;
  title: string;
  type: LessonType;
  order: number;
  duration_seconds: number | null;
  is_preview: boolean;
  /** Populated by the course-detail endpoint when the viewer is enrolled. */
  completed?: boolean;
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
  is_bookmarked: boolean;
  progress_pct: number;
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

export interface ChatMessageOut {
  id: string;
  course_id: string;
  body: string;
  created_at: string;
  author: UserPublic;
}

export interface TokenResponse {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  user: UserOut;
}
