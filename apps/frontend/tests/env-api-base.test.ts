import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Iter 102 regression: when the e2e container's browser loads the
// dev bundle from `http://web:3000`, `NEXT_PUBLIC_API_BASE_URL=
// http://localhost:8000` is baked in but `localhost` inside the
// container is the container itself, not the api. `env.ts`
// detects that case via `window.location.hostname === "web"` and
// rewrites the base to the docker-network hostname `api:8000`.
//
// This test pins the runtime check so an accidental revert
// (back to a constant) fails CI before login starts failing
// silently in the e2e run.

describe("env.API_BASE_URL hostname-aware switch", () => {
  const ORIGINAL_LOCATION = globalThis.window?.location;

  function setLocation(hostname: string) {
    Object.defineProperty(globalThis.window, "location", {
      value: { ...ORIGINAL_LOCATION, hostname },
      writable: true,
    });
  }

  beforeEach(() => {
    vi.resetModules();
  });

  afterEach(() => {
    Object.defineProperty(globalThis.window, "location", {
      value: ORIGINAL_LOCATION,
      writable: true,
    });
  });

  it("uses api:8000 when served from the docker `web` host", async () => {
    setLocation("web");
    const { env } = await import("../src/lib/env");
    expect(env.API_BASE_URL).toBe("http://api:8000");
    expect(env.WS_BASE_URL).toBe("ws://api:8000");
  });

  it("uses the bundled NEXT_PUBLIC base when served from localhost", async () => {
    setLocation("localhost");
    const { env } = await import("../src/lib/env");
    // The bundled default is http://localhost:8000 (unset
    // NEXT_PUBLIC_API_BASE_URL in this test environment).
    expect(env.API_BASE_URL).toBe(
      process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000",
    );
  });

  it("uses the bundled NEXT_PUBLIC base from any non-`web` hostname", async () => {
    setLocation("lumen.example.com");
    const { env } = await import("../src/lib/env");
    expect(env.API_BASE_URL).toBe(
      process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000",
    );
  });
});
