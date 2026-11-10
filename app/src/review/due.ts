import type { CardRow } from "./types";

/** New cards are always due; others once their due date has come. */
export function isDue(card: CardRow, now: Date): boolean {
  return card.fsrsState === "new" || (card.dueAt !== null && Date.parse(card.dueAt) <= now.getTime());
}

// A new card has no due date; it counts as due since it was made.
export function effectiveDue(card: CardRow): number {
  return Date.parse(card.dueAt ?? card.createdAt);
}
