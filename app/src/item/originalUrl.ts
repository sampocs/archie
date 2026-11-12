/**
 * The web page an item came from, or null when it has none: notes, books typed in, chat items and newsletters without
 * a web version store a placeholder address (`note:`, `book:`, `chat:`, `newsletter:`) instead of a page.
 */
export function originalUrl(url: string): string | null {
  return /^https?:\/\//i.test(url) ? url : null;
}
