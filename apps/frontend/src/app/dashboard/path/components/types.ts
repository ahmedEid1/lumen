/**
 * Wire types + query keys for the learning-path surface.
 *
 * These mirror the FastAPI response shapes in
 * ``apps/backend/app/api/v1/learning_path.py``. Held locally
 * (rather than appended to ``@/lib/api/endpoints``) to keep the
 * shared endpoints file under the orchestrator's control — once
 * the surface is generally available, the orchestrator can
 * promote these into the shared module.
 */

/** Stable kinds the agent emits for the "what to do today" hint. */
export type NextActionKind =
  | "start_lesson"
  | "review_due_cards"
  | "take_quiz";

/** Stable status values on a path step. */
export type StepStatus = "pending" | "in_progress" | "completed";

export interface LearningPathStepOut {
  id: string;
  position: number;
  milestone_name: string;
  milestone_weeks: string;
  course_id: string;
  course_slug: string;
  status: StepStatus;
}

export interface NextActionOut {
  course_slug: string | null;
  kind: NextActionKind | null;
}

export interface LearningPathOut {
  id: string;
  goal: string;
  rationale: string;
  status: "active" | "archived";
  next_action: NextActionOut | null;
  steps: LearningPathStepOut[];
  created_at: string;
  updated_at: string;
  replanned_at: string;
}

export interface TodayOut {
  course_slug: string | null;
  kind: NextActionKind | null;
  lesson_id_if_applicable: string | null;
  due_review_count: number;
}

/** Local TanStack Query keys — scoped under "path" so they
 *  never collide with the shared ``qk`` namespace. */
export const pathKeys = {
  active: ["me", "learning-path", "active"] as const,
  today: ["me", "learning-path", "today"] as const,
};
