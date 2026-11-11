import { ClientError } from "@/api/client";
import { isHttpUrl } from "@/capture/extractUrl";

/** What the owner says about a book they add: still reading it, or done. */
export type BookState = "reading" | "finished";
export const BOOK_STATES: readonly BookState[] = ["reading", "finished"];

/** The book `/books/lookup` matched: `author`, `year` and `coverUrl` may be unknown. */
export type BookMatch = { title: string; author: string | null; year: number | null; coverUrl: string | null; url: string };

/** The owner's choice under a match: Reading or Finished, and (with Finished) what stuck with them. */
export type BookChoice = { state: BookState; note: string };
export const DEFAULT_BOOK_CHOICE: BookChoice = { state: "reading", note: "" };

export const LOOKUP_OFFLINE_MESSAGE = "Couldn't look that up. Try again when you're online.";
export const LOOKUP_NOT_FOUND_MESSAGE = "No book found. Check the title.";

// A regex, not `new URL`: the share extension runs it, and React Native's URL polyfill is incomplete.
const GOODREADS_BOOK = /^https?:\/\/(?:www\.|m\.)?goodreads\.com\/book\/show\/([^/?#]+)/i;

/** The + sheet's rule: typed text that isn't an http(s) link is a book title to look up. */
export function isBookQuery(text: string): boolean {
  return text.trim() !== "" && !isHttpUrl(text);
}

/** What the + sheet treats as a book to look up: a title, or a Goodreads book link (which `/books/lookup` also reads). */
export function isBookModeText(text: string): boolean {
  return isBookQuery(text) || isGoodreadsBookUrl(text);
}

/** A shared Goodreads book page (goodreads.com/book/show/…): the share sheet adds it as a book. */
export function isGoodreadsBookUrl(url: string): boolean {
  return GOODREADS_BOOK.test(url.trim());
}

/**
 * The title a Goodreads book link spells in its path ("41817486-the-spy-and-the-traitor" → "the spy and the
 * traitor"); null when the path is only the id. The share sheet falls back to it when the lookup fails.
 */
export function goodreadsSlugTitle(url: string): string | null {
  const segment = GOODREADS_BOOK.exec(url.trim())?.[1];
  if (!segment) return null;
  const words = decodeURIComponent(segment)
    .replace(/^\d+[-.]?/, "")
    .replace(/[-_.]+/g, " ")
    .trim();
  return words || null;
}

/** The `/books/lookup` body as a match; null when it isn't one. */
export function parseBookMatch(body: unknown): BookMatch | null {
  const row = body as Record<string, unknown> | null;
  if (typeof row?.title !== "string" || typeof row.url !== "string") return null;
  return {
    title: row.title,
    url: row.url,
    author: typeof row.author === "string" ? row.author : null,
    year: typeof row.year === "number" ? row.year : null,
    coverUrl: typeof row.cover_url === "string" ? row.cover_url : null,
  };
}

/** The match card's line under the title: "Ben Macintyre · 2018", either part alone, or null with neither. */
export function bookMatchLine(match: Pick<BookMatch, "author" | "year">): string | null {
  const parts = [match.author, match.year === null ? null : String(match.year)].filter(
    (part): part is string => part !== null && part !== "",
  );
  return parts.length === 0 ? null : parts.join(" · ");
}

/** What the + sheet says when a lookup fails: a 404 is no match; anything else (offline, a 502) is unreachable. */
export function lookupErrorMessage(error: unknown): string {
  return error instanceof ClientError && error.status === 404 ? LOOKUP_NOT_FOUND_MESSAGE : LOOKUP_OFFLINE_MESSAGE;
}

/**
 * What the share sheet adds when the lookup of a shared Goodreads link fails: the page's own title when Safari sent
 * one, else the title in the link's path, else the link itself; never an author or cover.
 */
export function sharedBookFallback(url: string, sharedTitle: string | null): BookMatch {
  const title = sharedTitle?.trim() || goodreadsSlugTitle(url) || url;
  return { title, author: null, year: null, coverUrl: null, url };
}
