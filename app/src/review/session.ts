import { AHEAD_DAYS } from "./constants";
import { cardTopicId, isOpenQuiz, isReviewable, type ReviewData } from "./eligibility";
import type { CardRow } from "./types";

// Foundations first, then concepts and mechanisms, then rough numbers; anything else last; take cards sit with
// concepts. A placeholder order, to be tuned in the eval pass.
const ORDER_GROUP: Record<string, number> = { foundation: 0, concept: 1, mechanism: 1, take: 1, number: 2 };
const LAST_GROUP = 3;
const DAY_MS = 86_400_000;

export type SessionMode = "due" | "ahead" | "topic" | "source" | "take" | "card" | "quiz";
export const SESSION_MODES: readonly SessionMode[] = ["due", "ahead", "topic", "source", "take", "card", "quiz"];
export type SessionCard = { card: CardRow; wasDue: boolean };

/** New cards are always due; others once their due date has come. */
export function isDue(card: CardRow, now: Date): boolean {
  return card.fsrsState === "new" || (card.dueAt !== null && Date.parse(card.dueAt) <= now.getTime());
}

// A new card has no due date; it counts as due since it was made.
export function effectiveDue(card: CardRow): number {
  return Date.parse(card.dueAt ?? card.createdAt);
}

/** Session order: by kind group, then most overdue first, then by id so the order is stable. */
export function orderCards(cards: CardRow[]): CardRow[] {
  return [...cards].sort(
    (a, b) =>
      (ORDER_GROUP[a.kind] ?? LAST_GROUP) - (ORDER_GROUP[b.kind] ?? LAST_GROUP) ||
      effectiveDue(a) - effectiveDue(b) ||
      a.id.localeCompare(b.id),
  );
}

/** The cards a session shows, in order, each with whether it was due when the session began. */
export function buildSession(data: ReviewData, mode: SessionMode, id: string | null, now: Date): SessionCard[] {
  if (mode === "quiz") {
    return data.cards
      .filter((card) => isOpenQuiz(card, now))
      .sort((a, b) => Date.parse(a.createdAt) - Date.parse(b.createdAt))
      .map((card) => ({ card, wasDue: true }));
  }

  const reviewable = data.cards.filter((card) => isReviewable(card, data));
  const aheadLimit = now.getTime() + AHEAD_DAYS * DAY_MS;
  const chosen = reviewable.filter((card) => {
    switch (mode) {
      case "due":
        return isDue(card, now);
      case "ahead":
        return !isDue(card, now) && effectiveDue(card) <= aheadLimit;
      case "topic":
        return id !== null && cardTopicId(card, data) === id;
      case "source":
        return id !== null && card.sourceId === id;
      case "take":
        return id !== null && card.takeId === id;
      case "card":
        return card.id === id;
    }
  });
  return orderCards(chosen).map((card) => ({ card, wasDue: isDue(card, now) }));
}
