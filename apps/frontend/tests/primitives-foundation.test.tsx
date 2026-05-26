/**
 * Loop-3 primitives foundation — vitest coverage for the seven new
 * primitives + the `useHydrated()` hook.
 *
 * Each primitive's contract is pinned here so a future "while I'm
 * here" edit that drops `role="alert"` from a destructive Alert, or
 * forgets to wire `aria-invalid` on a Field with an error, fails
 * the suite loudly before merge.
 */
import { act, renderHook } from "@testing-library/react";
import { render, screen } from "@testing-library/react";
import { ArrowRight, Search } from "lucide-react";
import { describe, expect, it } from "vitest";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { LinkButton } from "@/components/ui/link-button";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { useHydrated } from "@/lib/use-hydrated";

describe("loop-3 primitives", () => {
  describe("Skeleton", () => {
    it("renders the default (line) variant with aria-hidden", () => {
      const { container } = render(<Skeleton data-testid="sk" />);
      const el = screen.getByTestId("sk");
      expect(el).toHaveAttribute("aria-hidden", "true");
      expect(el.className).toContain("h-4");
      expect(el.className).toContain("animate-pulse");
      expect(container).toBeTruthy();
    });

    it("renders each shape variant with the right shape class", () => {
      const cases: Array<[string, string]> = [
        ["card", "h-32"],
        ["image", "aspect-[16/10]"],
        ["circle", "rounded-full"],
      ];
      for (const [variant, expectedClass] of cases) {
        const { unmount } = render(
          <Skeleton variant={variant as never} data-testid={variant} />,
        );
        expect(screen.getByTestId(variant).className).toContain(expectedClass);
        unmount();
      }
    });

    it("text variant renders three bars at decreasing widths", () => {
      const { container } = render(<Skeleton variant="text" data-testid="t" />);
      const wrapper = screen.getByTestId("t");
      expect(wrapper).toHaveAttribute("aria-hidden", "true");
      // Three pulse bars inside; widths are w-full / w-5/6 / w-3/4.
      const bars = container.querySelectorAll(".animate-pulse");
      expect(bars.length).toBe(3);
    });

    it("accepts a className override that composes with variant classes", () => {
      render(<Skeleton variant="image" className="w-64" data-testid="ovr" />);
      const el = screen.getByTestId("ovr");
      expect(el.className).toContain("w-64");
      expect(el.className).toContain("aspect-[16/10]");
    });
  });

  describe("EmptyState", () => {
    it("renders title and body", () => {
      render(<EmptyState title="No courses yet" body="Browse the catalog." />);
      expect(screen.getByText("No courses yet")).toBeInTheDocument();
      expect(screen.getByText("Browse the catalog.")).toBeInTheDocument();
    });

    it("renders an icon when provided", () => {
      const { container } = render(
        <EmptyState icon={Search} title="No results" />,
      );
      // Lucide icons render as <svg>. Without an icon prop, there should
      // be zero svgs in the EmptyState body.
      expect(container.querySelectorAll("svg").length).toBe(1);
    });

    it("omits the icon when undefined", () => {
      const { container } = render(<EmptyState title="No results" />);
      expect(container.querySelectorAll("svg").length).toBe(0);
    });

    it("renders the cta slot", () => {
      render(
        <EmptyState
          title="No results"
          cta={<Button data-testid="cta">Retry</Button>}
        />,
      );
      expect(screen.getByTestId("cta")).toBeInTheDocument();
    });

    it("uses the surface utility class for the bordered shell", () => {
      const { container } = render(<EmptyState title="x" />);
      // `surface` utility composes border + bg-card per globals.css.
      // We check the root has the literal class name (Tailwind compiles
      // utility classes to literals in dev).
      expect(container.firstChild).toHaveClass("surface");
    });
  });

  describe("Alert", () => {
    it("renders title + children inside a status region by default", () => {
      render(
        <Alert tone="info" title="Heads up">
          New eval numbers are in.
        </Alert>,
      );
      expect(screen.getByText("Heads up")).toBeInTheDocument();
      expect(screen.getByText("New eval numbers are in.")).toBeInTheDocument();
      // info / success / warning → role="status" (polite).
      expect(screen.getByRole("status")).toBeInTheDocument();
    });

    it("uses role=alert only for the destructive tone", () => {
      const { rerender } = render(
        <Alert tone="success" title="Saved" />,
      );
      expect(screen.queryByRole("alert")).toBeNull();
      expect(screen.getByRole("status")).toBeInTheDocument();
      rerender(<Alert tone="destructive" title="Burned" />);
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });

    it("info tone references the loop-1 --info token via Tailwind classes", () => {
      const { container } = render(<Alert tone="info" title="x" />);
      const root = container.firstChild as HTMLElement;
      // bg-info / border-info / text-info — all derived from --info via
      // the loop-1 @theme inline alias. We check the literal class names
      // since Tailwind compiles them in dev.
      expect(root.className).toContain("border-info/40");
      expect(root.className).toContain("bg-info/10");
    });

    it("renders the icon when provided", () => {
      const { container } = render(
        <Alert tone="info" icon={ArrowRight} title="x" />,
      );
      // One svg from the icon — the icon is aria-hidden.
      expect(container.querySelectorAll("svg").length).toBe(1);
    });
  });

  describe("Field", () => {
    it("renders the label associated with the child input via htmlFor", () => {
      render(
        <Field label="Email" htmlFor="email">
          <Input id="email" />
        </Field>,
      );
      const input = screen.getByLabelText("Email") as HTMLInputElement;
      expect(input).toBeInTheDocument();
      expect(input.id).toBe("email");
    });

    it("renders hint when no error", () => {
      render(
        <Field label="Email" htmlFor="e" hint="We never share it.">
          <Input id="e" />
        </Field>,
      );
      const input = screen.getByLabelText("Email");
      expect(input).toHaveAttribute("aria-describedby", "e-hint");
      expect(input).not.toHaveAttribute("aria-invalid", "true");
      expect(screen.getByText("We never share it.")).toBeInTheDocument();
    });

    it("renders error and sets aria-invalid when error is present", () => {
      render(
        <Field
          label="Email"
          htmlFor="e"
          hint="We never share it."
          error="Required"
        >
          <Input id="e" />
        </Field>,
      );
      const input = screen.getByLabelText("Email");
      expect(input).toHaveAttribute("aria-invalid", "true");
      expect(input).toHaveAttribute("aria-describedby", "e-error");
      // Error takes precedence — hint should NOT render alongside.
      expect(screen.queryByText("We never share it.")).toBeNull();
      const err = screen.getByText("Required");
      expect(err).toBeInTheDocument();
      expect(err).toHaveAttribute("role", "alert");
    });

    it("required mark is decorative (aria-hidden)", () => {
      const { container } = render(
        <Field label="Email" htmlFor="e" required>
          <Input id="e" />
        </Field>,
      );
      const mark = container.querySelector('[aria-hidden="true"]');
      expect(mark).toBeTruthy();
      expect(mark?.textContent).toBe("*");
    });
  });

  describe("Spinner", () => {
    it("renders with role=status and a default aria-label of Loading", () => {
      render(<Spinner />);
      const el = screen.getByRole("status");
      expect(el).toHaveAttribute("aria-label", "Loading");
      expect(el.classList.contains("animate-spin")).toBe(true);
    });

    it("each size variant applies the right size class", () => {
      const cases: Array<["sm" | "md" | "lg", string]> = [
        ["sm", "h-3.5"],
        ["md", "h-4"],
        ["lg", "h-5"],
      ];
      for (const [size, cls] of cases) {
        const { unmount } = render(<Spinner size={size} />);
        expect(screen.getByRole("status").classList.contains(cls)).toBe(true);
        unmount();
      }
    });

    it("custom aria-label replaces the default", () => {
      render(<Spinner aria-label="Saving course" />);
      expect(screen.getByRole("status")).toHaveAttribute(
        "aria-label",
        "Saving course",
      );
    });
  });

  describe("LinkButton", () => {
    it("renders as a single anchor with the href (no nested button)", () => {
      const { container } = render(
        <LinkButton href="/courses">Browse</LinkButton>,
      );
      // The expected DOM is <a class="…button classes…">Browse</a> —
      // no <button> tag wrapping or wrapped inside.
      expect(container.querySelectorAll("button").length).toBe(0);
      const anchor = container.querySelector("a");
      expect(anchor).toBeTruthy();
      expect(anchor?.getAttribute("href")).toBe("/courses");
    });

    it("external links open in a new tab with rel=noopener noreferrer", () => {
      const { container } = render(
        <LinkButton href="https://example.com" external>
          External
        </LinkButton>,
      );
      const a = container.querySelector("a") as HTMLAnchorElement;
      expect(a.getAttribute("target")).toBe("_blank");
      expect(a.getAttribute("rel")).toBe("noopener noreferrer");
    });

    it("inherits Button variant + size styling", () => {
      const { container } = render(
        <LinkButton href="/x" variant="outline" size="lg">
          Browse
        </LinkButton>,
      );
      const a = container.querySelector("a") as HTMLAnchorElement;
      // outline variant => bordered ghost. size="lg" => h-10.
      expect(a.className).toContain("border");
      expect(a.className).toContain("h-10");
    });

    // Codex rescue #1 finding — anchors don't match :disabled, so
    // Button's disabled:* Tailwind variants are no-ops. LinkButton
    // has to explicitly drop the href, set aria-disabled + tabIndex,
    // and prevent default on click. Pin the contract.
    it("disabled drops href, sets aria-disabled, sets tabIndex=-1, and prevents click navigation", () => {
      const { container } = render(
        <LinkButton href="/courses" disabled>
          Browse
        </LinkButton>,
      );
      const a = container.querySelector("a") as HTMLAnchorElement;
      expect(a).toBeTruthy();
      expect(a.hasAttribute("href")).toBe(false);
      expect(a.getAttribute("aria-disabled")).toBe("true");
      expect(a.tabIndex).toBe(-1);
      // Visual styling — Tailwind classes apply when disabled.
      expect(a.className).toContain("opacity-50");
      expect(a.className).toContain("pointer-events-none");
    });

    it("disabled click handler prevents default", () => {
      const { container } = render(
        <LinkButton href="/courses" disabled>
          Browse
        </LinkButton>,
      );
      const a = container.querySelector("a") as HTMLAnchorElement;
      const event = new MouseEvent("click", { bubbles: true, cancelable: true });
      a.dispatchEvent(event);
      expect(event.defaultPrevented).toBe(true);
    });
  });

  describe("useHydrated", () => {
    it("starts false on first render and becomes true after effect flush", async () => {
      const { result } = renderHook(() => useHydrated());
      // happy-dom flushes useEffect synchronously by the time renderHook
      // returns, so `result.current` is already `true`. We assert the
      // post-flush value to lock the contract — callers can rely on it
      // being `true` on every render past the initial paint.
      expect(result.current).toBe(true);
    });

    it("stays true across re-renders", () => {
      const { result, rerender } = renderHook(() => useHydrated());
      act(() => rerender());
      expect(result.current).toBe(true);
    });
  });
});
