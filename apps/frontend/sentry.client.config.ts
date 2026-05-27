/**
 * Sentry / Glitchtip client-side instrumentation (L38).
 *
 * Loaded automatically by @sentry/nextjs from the project root.
 * DSN comes from NEXT_PUBLIC_SENTRY_DSN at build time (NEXT_PUBLIC_*
 * is the only env-var prefix Next exposes to client bundles); when
 * unset the SDK init becomes a no-op so dev/test builds don't
 * complain about a missing DSN.
 *
 * Mirrors the backend's L21-Sec scrubber via the shared `beforeSend`
 * shape — see `src/lib/sentry/scrubber.ts` for the field-level rules.
 */

import * as Sentry from "@sentry/nextjs";

import { beforeSendScrub } from "@/lib/sentry/scrubber";

if (process.env.NEXT_PUBLIC_SENTRY_DSN) {
  Sentry.init({
    dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
    environment: process.env.NEXT_PUBLIC_ENV ?? "production",
    // Keep sample rates conservative for a portfolio demo running on
    // Glitchtip's 1000 events/mo free tier. Performance + replay
    // would burn through the quota in a single recruiter visit.
    tracesSampleRate: 0,
    replaysSessionSampleRate: 0,
    replaysOnErrorSampleRate: 0,
    beforeSend(event) {
      return beforeSendScrub(event);
    },
    beforeBreadcrumb(breadcrumb) {
      // Drop any breadcrumb tagged `category: "tutor"` outright —
      // it's belt + braces with the beforeSend scrubber, but fewer
      // events with tutor-tagged content is fewer chances something
      // slips through.
      if (breadcrumb.category === "tutor") return null;
      return breadcrumb;
    },
  });
}
