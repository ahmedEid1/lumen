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
  markNotificationRead: (id: string, token?: string) =>
    api<{ ok: true }>(`/api/v1/me/notifications/${id}/read`, { method: "POST", token }),
  markAllNotificationsRead: (token?: string) =>
    api<{ ok: true; marked_read: number }>("/api/v1/me/notifications/read-all", {
      method: "POST",
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

