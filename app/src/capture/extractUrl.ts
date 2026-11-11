const URL_PATTERN = /https?:\/\/\S+/i;
const TRAILING_PUNCTUATION = /[).,"']+$/;

// Spotify and YouTube share text wraps the link in a sentence; take the first http(s) URL in it.
export function extractFirstUrl(text: string): string | null {
  const match = URL_PATTERN.exec(text);
  if (!match) return null;
  return match[0].replace(TRAILING_PUNCTUATION, "");
}

/** True for text that is an http(s) URL on its own (surrounding whitespace allowed). */
export function isHttpUrl(text: string): boolean {
  try {
    const protocol = new URL(text.trim()).protocol;
    return protocol === "http:" || protocol === "https:";
  } catch {
    return false;
  }
}
