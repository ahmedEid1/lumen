/**
 * Loop-4 AuthCard primitive — vitest coverage.
 *
 * AuthCard owns the seven byte-identical auth chromes the audit named
 * (cross-cutting #1). This test pins the shape so a future "while I'm
 * here" edit can't quietly drift the cartouche, the heading typeface,
 * or the wrapper width without the suite going red.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AuthCard } from "@/components/ui/auth-card";

describe("AuthCard", () => {
  it("renders the cartouche, heading, and subtitle in the documented order", () => {
    render(
      <AuthCard
        cartouche="AUTH.LOGIN.CARTOUCHE"
        heading="Sign in"
        subtitle="Welcome back"
      >
        <p>form goes here</p>
      </AuthCard>,
    );
    const cartouche = screen.getByText("AUTH.LOGIN.CARTOUCHE");
    const heading = screen.getByRole("heading", { level: 1 });
    const subtitle = screen.getByText("Welcome back");
    expect(cartouche).toBeInTheDocument();
    expect(heading).toHaveTextContent("Sign in");
    expect(subtitle).toBeInTheDocument();
    // The cartouche element should appear BEFORE the heading in
    // document order — DOM-order assertion via compareDocumentPosition.
    expect(
      cartouche.compareDocumentPosition(heading) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    // Children render below the header.
    expect(screen.getByText("form goes here")).toBeInTheDocument();
  });

  it("omits the subtitle paragraph when subtitle is undefined", () => {
    render(
      <AuthCard cartouche="CART" heading="Title">
        <p>x</p>
      </AuthCard>,
    );
    expect(screen.queryByText("Welcome back")).toBeNull();
    // The header still renders cartouche + heading.
    expect(screen.getByText("CART")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Title");
  });

  it("cartouche carries the Workbench mono / uppercase / muted treatment", () => {
    render(
      <AuthCard cartouche="CART" heading="Title">
        <p>x</p>
      </AuthCard>,
    );
    const el = screen.getByText("CART");
    // Compiled Tailwind class names — load-bearing for the
    // visual identity.
    expect(el.className).toContain("font-mono");
    expect(el.className).toContain("uppercase");
    expect(el.className).toContain("text-muted-foreground");
  });

  it("heading uses font-display + h1 tracking", () => {
    render(
      <AuthCard cartouche="CART" heading="Title">
        <p>x</p>
      </AuthCard>,
    );
    const h1 = screen.getByRole("heading", { level: 1 });
    expect(h1.className).toContain("font-display");
    expect(h1.className).toContain("tracking-tight");
    expect(h1.className).toContain("text-3xl");
  });

  it("outer wrapper defaults to max-w-[440px]", () => {
    const { container } = render(
      <AuthCard cartouche="C" heading="H">
        <p>x</p>
      </AuthCard>,
    );
    const outer = container.firstChild as HTMLElement;
    expect(outer.className).toContain("max-w-[440px]");
  });

  it("className override replaces the default width via tailwind-merge", () => {
    const { container } = render(
      <AuthCard cartouche="C" heading="H" className="max-w-[520px]">
        <p>x</p>
      </AuthCard>,
    );
    const outer = container.firstChild as HTMLElement;
    // `cn()` uses tailwind-merge under the hood. When a callsite
    // passes `max-w-[520px]` and the default is `max-w-[440px]`,
    // tailwind-merge dedupes to the override (last wins) — the
    // default is REPLACED, not composed. /verify/[id]/page.tsx
    // relies on this to widen the chrome to 520px.
    expect(outer.className).toContain("max-w-[520px]");
    expect(outer.className).not.toContain("max-w-[440px]");
  });

  it("card chrome matches the byte-identical pre-migration shape", () => {
    // The bordered card sits inside the outer wrapper. Confirm the
    // exact class set the seven auth surfaces used to hand-roll:
    //   rounded-md border border-border bg-card p-8
    const { container } = render(
      <AuthCard cartouche="C" heading="H">
        <p>x</p>
      </AuthCard>,
    );
    const card = container.querySelector("[class*='rounded-md']") as HTMLElement;
    expect(card).toBeTruthy();
    expect(card.className).toContain("rounded-md");
    expect(card.className).toContain("border-border");
    expect(card.className).toContain("bg-card");
    expect(card.className).toContain("p-8");
  });
});
