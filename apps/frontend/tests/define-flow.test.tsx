/**
 * S3.11 — define → build → learn flow (FR-DEFINE-05/07/09/16/17).
 *
 * Drives the `/learn/define` page (the canonical learner-author build entry,
 * NOT `/studio`) across its three phases against a real QueryClient with the
 * endpoints mocked (byok-model-page.test.tsx idioms):
 *
 *   1. intake   — the goal-intake chat renders the accumulated brief, posts
 *                 turns, and surfaces the bounded turn cap (R-M10).
 *   2. review   — the brief-review form requires an EXPLICIT confirm before a
 *                 build starts (FR-DEFINE-07: never auto), and shows the
 *                 estimate + "a private course will be created" note
 *                 (FR-DEFINE-16) BEFORE the build.
 *   3. building — kicking the build off renders progress via the reused
 *                 CourseDraftTrace timeline (FR-DEFINE-17); a build_failed
 *                 surface renders on failure with a re-run affordance.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type {
  BriefOut,
  CourseDetail,
  DraftFromBriefResponse,
  GoalTurnResponse,
  UserOut,
} from "@/lib/api/types";
import type { DraftTraceResponse } from "@/lib/api/endpoints";

// Shared router spy (override the global setup.ts next/navigation mock with a
// stable push spy we can assert the learn deep-link against).
const pushMock = vi.fn();
const replaceMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: pushMock,
    replace: replaceMock,
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/learn/define",
  useParams: () => ({}),
  redirect: vi.fn(),
  notFound: vi.fn(),
}));

// Mutable auth state — flip per spec.
const authState: { user: UserOut | null; token: string | null; ready: boolean } = {
  user: null,
  token: "test-token",
  ready: true,
};
vi.mock("@/lib/auth/store", () => ({ useAuth: () => authState }));

// Endpoint spies feeding the page's mutations/queries.
const startGoal = vi.fn<[string], Promise<GoalTurnResponse>>();
const takeTurn = vi.fn<[string, string], Promise<GoalTurnResponse>>();
const finalize = vi.fn<[], Promise<BriefOut>>();
const draftFromBrief = vi.fn<[string], Promise<DraftFromBriefResponse>>();
const cancelBuild = vi.fn(async () => ({ ok: true as const }));
const draftTrace = vi.fn<[string], Promise<DraftTraceResponse>>();
const courseGet = vi.fn<[string], Promise<CourseDetail>>();
vi.mock("@/lib/api/endpoints", () => ({
  Define: {
    startGoal: (goal: string) => startGoal(goal),
    takeTurn: (sid: string, msg: string) => takeTurn(sid, msg),
    finalize: () => finalize(),
    draftFromBrief: (id: string) => draftFromBrief(id),
    cancelBuild: (_id: string) => cancelBuild(),
  },
  AI: { draftTrace: (cid: string) => draftTrace(cid) },
  Courses: { get: (key: string) => courseGet(key) },
}));

import DefinePage from "@/app/learn/define/page";

function mkUser(): UserOut {
  return {
    id: "u1",
    full_name: "Lena Owner",
    avatar_url: null,
    bio: null,
    role: "user",
    email: "u@lumen.test",
    is_active: true,
    email_verified_at: null,
    created_at: "2026-01-01T00:00:00Z",
  };
}

function mkTurn(over: Partial<GoalTurnResponse> = {}): GoalTurnResponse {
  return {
    session_id: "sess1",
    assistant_message: "What is your current React level?",
    accumulated_brief: { goal_summary: "Get good at React" },
    turns_used: 1,
    turns_remaining: 5,
    converged: false,
    ...over,
  };
}

function mkBrief(over: Partial<BriefOut> = {}): BriefOut {
  return {
    id: "brief1",
    level: "beginner",
    time_budget_hours: 10,
    sessions_per_week: 3,
    prior_knowledge: "Some JS",
    desired_outcomes: ["Build a SPA", "Understand hooks"],
    goal_summary: "Get good at React",
    suggested_subject: "Personal / Self-directed",
    language: "en",
    finalized_at: "2026-06-05T00:00:00Z",
    ...over,
  };
}

function mkTrace(over: Partial<DraftTraceResponse> = {}): DraftTraceResponse {
  return {
    course_id: "c1",
    draft_id: "d1",
    steps: [
      {
        id: "t1",
        draft_id: "d1",
        course_id: "c1",
        step: "researcher",
        step_index: 0,
        status: "ok",
        duration_ms: 120,
        payload: { response_summary: "Researched React fundamentals" },
        created_at: "2026-06-05T00:00:00Z",
      },
    ],
    ...over,
  };
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <DefinePage />
    </QueryClientProvider>,
  );
}

describe("DefinePage (S3.11 define→build→learn)", () => {
  beforeEach(() => {
    pushMock.mockClear();
    replaceMock.mockClear();
    startGoal.mockReset();
    takeTurn.mockReset();
    finalize.mockReset();
    draftFromBrief.mockReset();
    cancelBuild.mockClear();
    draftTrace.mockReset();
    courseGet.mockReset();
    authState.user = mkUser();
    authState.token = "test-token";
    authState.ready = true;
  });
  afterEach(() => vi.restoreAllMocks());

  it("redirects anonymous users to /login?next=/learn/define", async () => {
    authState.user = null;
    renderPage();
    await waitFor(() =>
      expect(replaceMock).toHaveBeenCalledWith("/login?next=/learn/define"),
    );
    expect(startGoal).not.toHaveBeenCalled();
  });

  it("starts a goal session, accumulates the brief, and surfaces the turn cap", async () => {
    const user = userEvent.setup();
    startGoal.mockResolvedValue(mkTurn());
    // The second turn hits the cap: turns_remaining 0 + converged.
    takeTurn.mockResolvedValue(
      mkTurn({
        assistant_message: "Got it — here is your plan.",
        accumulated_brief: { goal_summary: "Get good at React", level: "beginner" },
        turns_used: 6,
        turns_remaining: 0,
        converged: true,
      }),
    );

    renderPage();

    // Start the conversation.
    const goalInput = await screen.findByLabelText(/what do you want to learn/i);
    await user.type(goalInput, "I want to get good at React");
    await user.click(screen.getByRole("button", { name: /start/i }));

    // The assistant message + the accumulated brief render.
    expect(await screen.findByText(/current React level/i)).toBeInTheDocument();
    expect(startGoal).toHaveBeenCalledWith("I want to get good at React");
    // aria-live region present for screen readers (FR-A11Y-01).
    expect(screen.getByTestId("goal-chat-log")).toHaveAttribute("aria-live", "polite");

    // Reply once — drives to the cap.
    const replyInput = await screen.findByLabelText(/your reply/i);
    await user.type(replyInput, "beginner");
    await user.click(screen.getByRole("button", { name: /^send$/i }));

    // Turn cap surfaced: the reply input disappears, a cap notice shows.
    expect(await screen.findByTestId("turn-cap-notice")).toBeInTheDocument();
    expect(takeTurn).toHaveBeenCalledWith("sess1", "beginner");
  });

  it("requires an explicit confirm before the build starts (FR-DEFINE-07)", async () => {
    const user = userEvent.setup();
    // Converge immediately on start so the Review step is reachable.
    startGoal.mockResolvedValue(
      mkTurn({ converged: true, turns_remaining: 3, turns_used: 3 }),
    );
    finalize.mockResolvedValue(mkBrief());

    renderPage();

    await user.type(
      await screen.findByLabelText(/what do you want to learn/i),
      "React",
    );
    await user.click(screen.getByRole("button", { name: /start/i }));

    // Converged → a "Review brief" affordance, then the review form.
    await user.click(await screen.findByRole("button", { name: /review/i }));

    // Review form shows the estimate + the private-course note BEFORE build.
    const review = await screen.findByTestId("brief-review");
    // FR-DEFINE-16: estimate (module count from the 10h budget → mid band 4).
    expect(within(review).getByTestId("build-estimate")).toHaveTextContent(/4/);
    // FR-DEFINE-11 note: a private course will be created.
    expect(within(review).getByTestId("private-note")).toBeInTheDocument();

    // No build has been kicked off merely by reaching the review screen.
    expect(draftFromBrief).not.toHaveBeenCalled();

    // The explicit confirm button triggers the build.
    draftFromBrief.mockResolvedValue({
      course_id: "c1",
      slug: "react-from-scratch",
      module_count: 4,
      lesson_count: 12,
      draft_id: "d1",
      revisions_used: 1,
    });
    draftTrace.mockResolvedValue(mkTrace());
    courseGet.mockResolvedValue({ status: "draft" } as CourseDetail);

    await user.click(
      within(review).getByRole("button", { name: /build my course/i }),
    );
    await waitFor(() => expect(finalize).toHaveBeenCalled());
    await waitFor(() => expect(draftFromBrief).toHaveBeenCalledWith("brief1"));
  });

  it("renders build progress via the trace timeline and deep-links to learn on success", async () => {
    const user = userEvent.setup();
    startGoal.mockResolvedValue(mkTurn({ converged: true }));
    finalize.mockResolvedValue(mkBrief());
    draftFromBrief.mockResolvedValue({
      course_id: "c1",
      slug: "react-from-scratch",
      module_count: 4,
      lesson_count: 12,
      draft_id: "d1",
      revisions_used: 1,
    });
    draftTrace.mockResolvedValue(mkTrace());
    courseGet.mockResolvedValue({ status: "draft" } as CourseDetail);

    renderPage();
    await user.type(
      await screen.findByLabelText(/what do you want to learn/i),
      "React",
    );
    await user.click(screen.getByRole("button", { name: /start/i }));
    await user.click(await screen.findByRole("button", { name: /review/i }));
    await user.click(
      await screen.findByRole("button", { name: /build my course/i }),
    );

    // Build progress reuses the CourseDraftTrace timeline.
    expect(await screen.findByTestId("draft-trace-timeline")).toBeInTheDocument();

    // On success a deep-link into the owner self-learn surface is offered.
    const learnLink = await screen.findByRole("link", {
      name: /start learning|go to my course|learn/i,
    });
    expect(learnLink).toHaveAttribute("href", "/learn/react-from-scratch");
  });

  it("renders a clean build_failed surface with a re-run affordance", async () => {
    const user = userEvent.setup();
    startGoal.mockResolvedValue(mkTurn({ converged: true }));
    finalize.mockResolvedValue(mkBrief());
    // The build call fails with a normalized define.build_failed error.
    const err = Object.assign(new Error("The build did not complete."), {
      status: 502,
      code: "define.build_failed",
    });
    draftFromBrief.mockRejectedValue(err);

    renderPage();
    await user.type(
      await screen.findByLabelText(/what do you want to learn/i),
      "React",
    );
    await user.click(screen.getByRole("button", { name: /start/i }));
    await user.click(await screen.findByRole("button", { name: /review/i }));
    await user.click(
      await screen.findByRole("button", { name: /build my course/i }),
    );

    // A failure surface, not a half-course.
    expect(await screen.findByTestId("build-failed")).toBeInTheDocument();
    // A retry affordance re-runs the (idempotent) build.
    expect(
      screen.getByRole("button", { name: /try again|retry|rebuild/i }),
    ).toBeInTheDocument();
  });
});
