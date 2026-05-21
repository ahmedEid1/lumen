/** Backoff schedule shared between the chat WebSocket and its tests. */
export const BACKOFF_STEPS_MS = [1_000, 2_000, 4_000, 8_000, 15_000, 30_000];

/** WebSocket close codes the server uses to refuse a session — do not retry. */
const TERMINAL_CLOSE_CODES = new Set([4401, 4403, 4404]);

export function nextBackoff(attempt: number): number {
  if (attempt < 0) return BACKOFF_STEPS_MS[0];
  return BACKOFF_STEPS_MS[Math.min(attempt, BACKOFF_STEPS_MS.length - 1)];
}

export function shouldRetry(code: number | undefined): boolean {
  if (code == null) return true;
  return !TERMINAL_CLOSE_CODES.has(code);
}
