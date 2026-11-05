/**
 * The full email as markdown with every line its own paragraph: emails often arrive one line per paragraph, and the
 * markdown renderer would otherwise join consecutive lines into one block.
 */
export function emailParagraphs(text: string): string {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .join("\n\n");
}
