/** A primer artifact's stored JSON, and how long it takes to read. */

const WORDS_PER_MINUTE = 220;

export function primerMarkdown(content: string): string {
  return (JSON.parse(content) as { markdown: string }).markdown;
}

export function wordCount(text: string): number {
  return text.split(/\s+/).filter(Boolean).length;
}

/** The primer button's "N min": words / 220, rounded up, at least 1. */
export function readingMinutes(words: number): number {
  return Math.max(1, Math.ceil(words / WORDS_PER_MINUTE));
}
