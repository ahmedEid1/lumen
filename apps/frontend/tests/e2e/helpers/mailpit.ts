/**
 * Mailpit helpers — fetch transactional emails from the dev mail
 * service so e2e tests can complete email-bound flows (verification
 * link, password-reset link) without poking the backend.
 *
 * Why this exists instead of a backend dev-only "give me the latest
 * token" endpoint: adding a backend endpoint just for testing is the
 * kind of footgun the spec calls out (H6 owns auth-surface security).
 * Mailpit is already in docker-compose.yml as the SMTP catcher
 * (axllent/mailpit:v1.20), exposes a REST API on :8025, and Lumen's
 * Celery email task wires straight to it (SMTP_HOST=mail / 1025). The
 * verification + reset flows put the token in the link query string,
 * so reading the latest message and pulling ``?token=`` out is enough.
 *
 * Defaults:
 *   - MAILPIT_BASE_URL defaults to http://localhost:8025 (host mapping
 *     from docker-compose.yml). In CI we keep the same mapping; if the
 *     host name ever changes we override via the env var.
 *   - The poll loop is generous (10s, every 250ms) because Celery
 *     dispatch hops through Redis and Mailpit's ingest is async.
 */

const DEFAULT_BASE = process.env.MAILPIT_BASE_URL ?? "http://localhost:8025";

interface MailpitMessageSummary {
  ID: string;
  To: Array<{ Address: string }>;
  From: { Address: string };
  Subject: string;
  Created: string;
}

interface MailpitMessagesResponse {
  messages: MailpitMessageSummary[];
  total: number;
}

interface MailpitMessageDetail {
  ID: string;
  Subject: string;
  Text: string;
  HTML: string;
}

async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`mailpit ${res.status} ${res.statusText} from ${url}`);
  }
  return (await res.json()) as T;
}

/**
 * Return the latest message addressed to ``email`` that matches the
 * given ``subjectMatcher``. Polls up to ``timeoutMs``.
 */
export async function waitForMessage(opts: {
  to: string;
  subjectMatcher: RegExp;
  baseUrl?: string;
  timeoutMs?: number;
  pollIntervalMs?: number;
}): Promise<MailpitMessageDetail> {
  const baseUrl = opts.baseUrl ?? DEFAULT_BASE;
  const timeoutMs = opts.timeoutMs ?? 15_000;
  const pollIntervalMs = opts.pollIntervalMs ?? 250;
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    const list = await fetchJson<MailpitMessagesResponse>(
      `${baseUrl}/api/v1/messages?limit=50`,
    );
    const match = list.messages.find(
      (m) =>
        m.To.some((t) => t.Address.toLowerCase() === opts.to.toLowerCase()) &&
        opts.subjectMatcher.test(m.Subject),
    );
    if (match) {
      const detail = await fetchJson<MailpitMessageDetail>(
        `${baseUrl}/api/v1/message/${match.ID}`,
      );
      return detail;
    }
    await new Promise((r) => setTimeout(r, pollIntervalMs));
  }
  throw new Error(
    `Timed out (${timeoutMs}ms) waiting for mail to ${opts.to} matching ${opts.subjectMatcher}`,
  );
}

/**
 * Extract the ``token`` query-string value from the first link in the
 * email body that matches ``linkMatcher``. Works against both the
 * plain-text and HTML bodies — the email templates duplicate the link
 * across both, so checking text is enough but we fall back to HTML
 * for safety.
 */
export function extractTokenFromMessage(
  msg: { Text?: string; HTML?: string },
  linkMatcher: RegExp,
): string {
  const haystack = `${msg.Text ?? ""}\n${msg.HTML ?? ""}`;
  const urlRe = new RegExp(linkMatcher.source + "\\S*", "i");
  const urlMatch = haystack.match(urlRe);
  if (!urlMatch) {
    throw new Error(
      `No link matching ${linkMatcher} in message body. Head: ${haystack.slice(0, 300)}`,
    );
  }
  const tokenMatch = urlMatch[0].match(/[?&]token=([^&\s"<>]+)/);
  if (!tokenMatch) {
    throw new Error(
      `Found link but no ?token= query param: ${urlMatch[0].slice(0, 200)}`,
    );
  }
  // The URL is HTML-escaped in the HTML body (``&amp;``); decode the
  // bare ampersand back so the token is usable verbatim.
  return decodeURIComponent(tokenMatch[1]).replace(/&amp;/g, "&");
}

/**
 * Delete every message in Mailpit. Tests call this in ``beforeAll``
 * so the poller doesn't trip over stale envelopes from a previous run.
 */
export async function clearMailpit(baseUrl: string = DEFAULT_BASE): Promise<void> {
  const res = await fetch(`${baseUrl}/api/v1/messages`, { method: "DELETE" });
  if (!res.ok && res.status !== 404) {
    throw new Error(`mailpit clear ${res.status} ${res.statusText}`);
  }
}

export const MAILPIT_BASE_URL = DEFAULT_BASE;
