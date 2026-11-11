import { apiFetch, NetworkError } from "@/api/client";

import { parseBookMatch, type BookMatch } from "./books";

// A hung lookup must fail like an offline one, so the sheet shows its message instead of spinning.
const LOOKUP_TIMEOUT_MS = 15_000;

/**
 * Looks a title or a Goodreads book URL up through `POST /books/lookup`. Throws a `ClientError` (404) when nothing
 * matched and a `NetworkError` when the lookup can't be reached (offline, a 502 or the timeout).
 */
export async function lookupBook(query: string, sessionKey: string | null): Promise<BookMatch> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), LOOKUP_TIMEOUT_MS);
  try {
    const body = await apiFetch("/books/lookup", {
      method: "POST",
      body: { query: query.trim() },
      sessionKey,
      signal: controller.signal,
    });
    const match = parseBookMatch(body);
    if (!match) throw new NetworkError("malformed /books/lookup response");
    return match;
  } finally {
    clearTimeout(timer);
  }
}
