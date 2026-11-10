/** A card's detail as bullet lines: the stored "\n"-joined string split, trimmed, blanks dropped. */
export function detailLines(detail: string): string[] {
  return detail
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line !== "");
}
