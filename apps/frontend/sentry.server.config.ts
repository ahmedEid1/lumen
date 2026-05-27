/**
 * Sentry server-side instrumentation (L38).
 *
 * Loaded by @sentry/nextjs in the Node.js runtime (server actions,
 * RSC, API routes). DSN comes from SENTRY_DSN (NOT NEXT_PUBLIC_ —
 * the server-side DSN never reaches the browser bundle).
 */

import * as Sentry from "@sentry/nextjs";

import { beforeSendScrub } from "@/lib/sentry/scrubber";

if (process.env.SENTRY_DSN) {
  Sentry.init({
    dsn: process.env.SENTRY_DSN,
    environment: process.env.ENV ?? process.env.NODE_ENV ?? "production",
    tracesSampleRate: 0,
    beforeSend(event) {
      return beforeSendScrub(event);
    },
    beforeBreadcrumb(breadcrumb) {
      if (breadcrumb.category === "tutor") return null;
      return breadcrumb;
    },
  });
}
