import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

// happy-dom doesn't implement these Element methods that Radix Select
// + DropdownMenu reach for during portal positioning + active-item
// scroll. Stub them as no-ops so the open-content branches actually
// render and `findByRole("option")` resolves. Without these stubs
// Radix Select's open flow throws before mounting the portal.
if (typeof window !== "undefined") {
  // hasPointerCapture: Radix uses this on focus management.
  if (!Element.prototype.hasPointerCapture) {
    Element.prototype.hasPointerCapture = () => false;
  }
  if (!Element.prototype.scrollIntoView) {
    Element.prototype.scrollIntoView = () => undefined;
  }
  if (!Element.prototype.releasePointerCapture) {
    Element.prototype.releasePointerCapture = () => undefined;
  }
}

// components under test pull `useRouter` /
// `useSearchParams` / `usePathname` from `next/navigation`. Outside
// a real Next.js page tree those hooks throw
// `invariant expected app router to be mounted`. Stub them at the
// module level so every spec gets a no-op router for free.
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/",
  useParams: () => ({}),
  redirect: vi.fn(),
  notFound: vi.fn(),
}));

// components like HeaderSearch use `useT()` which
// throws outside a LocaleProvider. Stub the provider hooks to
// return the real English string for the key (not the key
// itself) so accessibility-name selectors keep matching.
vi.mock("@/lib/i18n/provider", async () => {
  const { en } = await import("../src/lib/i18n/messages/en");
  return {
    useLocale: () => ({ locale: "en", setLocale: vi.fn() }),
    useT:
      () =>
      (key: string, vars?: Record<string, string | number>): string => {
        let s = (en as Record<string, string>)[key] ?? key;
        if (vars) {
          for (const [k, v] of Object.entries(vars)) {
            s = s.replaceAll(`{${k}}`, String(v));
          }
        }
        return s;
      },
    LocaleProvider: ({ children }: { children: React.ReactNode }) => children,
  };
});
