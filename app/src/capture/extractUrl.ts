const URL_PATTERN = /https?:\/\/\S+/i;
const TRAILING_PUNCTUATION = /[).,"']+$/;

// Spotify and YouTube share text wraps the link in a sentence; take the first http(s) URL in it.
export function extractFirstUrl(text: string): string | null {
  const match = URL_PATTERN.exec(text);
  if (!match) return null;
  return match[0].replace(TRAILING_PUNCTUATION, "");
}
