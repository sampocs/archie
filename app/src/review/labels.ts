import type { ReviewGrade } from "./types";

export const KIND_LABELS: Record<string, string> = {
  foundation: "Foundation",
  concept: "Concept",
  mechanism: "Mechanism",
  number: "Rough number",
  quiz: "News",
  take: "Take",
};

export const GRADE_LABELS: Record<ReviewGrade, string> = { got_it: "Got it", partly: "Partly", missed: "Missed" };

/** "1 card" / "5 cards". */
export function cardsWord(count: number): string {
  return count === 1 ? "1 card" : `${count} cards`;
}
