export type FactSegment = { text: string; figure: boolean };

const UNITS = "billion|million|trillion|thousand|bps|bp";
// Clock times come first so "5am" is claimed as plain text before the figure branch can take the "5".
const TIME_OR_FIGURE = new RegExp(
  `(\\d{1,2}(?::\\d{2})?\\s?[ap]m\\b)|([+−]?\\$?\\d[\\d,]*(?:\\.\\d+)?(?:%|k\\+?|\\+|\\s(?:${UNITS})\\b)?)`,
  "gi",
);

/**
 * Splits a Rough-numbers sentence into plain and figure runs so the figures can be set in mono.
 * A figure keeps its sign, `$`, and unit ("$6.34 billion", "+6.0 bps", "$45k+", "98%") as one run. Clock times
 * ("5am") are context for the number, not the number, so they stay plain; so do digits glued to a word (Q3, H100).
 */
export function splitFacts(sentence: string): FactSegment[] {
  const segments: FactSegment[] = [];
  let cursor = 0;

  for (const match of sentence.matchAll(TIME_OR_FIGURE)) {
    const start = match.index ?? 0;
    const glued = /[A-Za-z]/.test(sentence[start - 1] ?? "");
    if (match[2] === undefined || glued) continue;

    if (start > cursor) segments.push({ text: sentence.slice(cursor, start), figure: false });
    segments.push({ text: match[2], figure: true });
    cursor = start + match[2].length;
  }
  if (cursor < sentence.length) segments.push({ text: sentence.slice(cursor), figure: false });

  return segments;
}
