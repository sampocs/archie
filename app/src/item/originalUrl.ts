/**
 * The web page an item came from, or null when it has none: Bear notes, books the lookup didn't match, chat items and
 * newsletters without a web version store a placeholder address (`bear:`, `book:`, `chat:`, `newsletter:`) instead.
 */
export function originalUrl(url: string): string | null {
  return /^https?:\/\//i.test(url) ? url : null;
}
