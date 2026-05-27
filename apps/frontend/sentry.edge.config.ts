/**
 * Sentry edge-runtime instrumentation (L38).
 *
 * Loaded by @sentry/nextjs in the edge runtime (middleware,
 * opengraph-image at request time). Same DSN as the server config
 * — only the import target differs because the edge runtime has a
 * narrower API surface than Node.
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
