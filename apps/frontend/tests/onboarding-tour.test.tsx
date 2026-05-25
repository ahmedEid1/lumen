import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { OnboardingTour } from "@/components/onboarding/onboarding-tour";
import type { TourStep } from "@/lib/onboarding/steps";

// Minimal English keys that match what the tour renders. The harness
// setup (tests/setup.ts) maps ``useT`` to the real English dictionary,
// so we hand the tour real ``MessageKey`` values and assert on the
// English strings they resolve to.
const STEPS: TourStep[] = [
  { title: "onboarding.learner.s1.title", body: "onboarding.learner.s1.body" },
  { title: "onboarding.learner.s2.title", body: "onboarding.learner.s2.body" },
  { title: "onboarding.learner.s3.title", body: "onboarding.learner.s3.body" },
];

const KEY = "lumen.onboarding.test.dismissed";

describe("OnboardingTour", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
  });

  it("renders the first step on mount when the dismissal flag is absent", async () => {
    render(<OnboardingTour steps={STEPS} storageKey={KEY} />);
    // Step 1 title is the learner welcome copy.
    expect(await screen.findByText(/welcome to lumen/i)).toBeInTheDocument();
    // Step counter reflects 1 of 3.
    expect(screen.getByText(/step 1 of 3/i)).toBeInTheDocument();
    // Primary CTA on a non-final step says Next, not Got it.
    expect(screen.getByRole("button", { name: /next/i })).toBeInTheDocument();
  });

  it("advances to the next step when Next is clicked", async () => {
    render(<OnboardingTour steps={STEPS} storageKey={KEY} />);
    const user = userEvent.setup();
    await screen.findByText(/welcome to lumen/i);

    await user.click(screen.getByRole("button", { name: /next/i }));

    expect(await screen.findByText(/ask the tutor/i)).toBeInTheDocument();
    expect(screen.getByText(/step 2 of 3/i)).toBeInTheDocument();
  });

  it("on the final step the CTA reads Got it and dismissing hides the tour + persists the flag", async () => {
    render(<OnboardingTour steps={STEPS} storageKey={KEY} />);
    const user = userEvent.setup();
    await screen.findByText(/welcome to lumen/i);

    // Advance to step 3.
    await user.click(screen.getByRole("button", { name: /next/i }));
    await screen.findByText(/ask the tutor/i);
    await user.click(screen.getByRole("button", { name: /next/i }));
    await screen.findByText(/build a streak/i);

    // CTA flips to Got it on the last step.
    const done = screen.getByRole("button", { name: /got it/i });
    await user.click(done);

    // Dialog is gone.
    expect(screen.queryByRole("dialog")).toBeNull();
    // Flag was persisted so the tour stays dismissed next time.
    expect(window.localStorage.getItem(KEY)).toBe("1");
  });

  it("does not render when the dismissal flag is already set", () => {
    window.localStorage.setItem(KEY, "1");
    render(<OnboardingTour steps={STEPS} storageKey={KEY} />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("Skip dismisses and persists the flag", async () => {
    render(<OnboardingTour steps={STEPS} storageKey={KEY} />);
    const user = userEvent.setup();
    await screen.findByText(/welcome to lumen/i);

    await user.click(screen.getByRole("button", { name: /dismiss the tour/i }));

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(window.localStorage.getItem(KEY)).toBe("1");
  });
});
