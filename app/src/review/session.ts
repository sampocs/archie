import { missedCards, shufflePick } from "./browse";
import { AHEAD_DAYS, SHUFFLE_COUNT } from "./constants";
import { dailyPlan, moreCards } from "./dailyCap";
import { effectiveDue, isDue } from "./due";
import { cardTopicId, isOpenQuiz, isReviewable, type ReviewData } from "./eligibility";
import type { CardRow } from "./types";

// Foundations first, then concepts and mechanisms, then rough numbers; anything else last; take cards sit with
// concepts. A placeholder order, to be tuned in the eval pass.
const ORDER_GROUP: Record<string, number> = { foundation: 0, concept: 1, mechanism: 1, take: 1, number: 2 };
const LAST_GROUP = 3;
const DAY_MS = 86_400_000;

export type SessionMode =
  | "due"
  | "more"
  | "ahead"
  | "topic"
  | "source"
  | "take"
  | "card"
  | "quiz"
  | "shuffle"
  | "missed";
export const SESSION_MODES: readonly SessionMode[] = [
  "due",
  "more",
  "ahead",
  "topic",
  "source",
  "take",
  "card",
  "quiz",
  "shuffle",
  "missed",
];
export type SessionCard = { card: CardRow; wasDue: boolean };

/** Session order: by kind group, then most overdue first, then by id so the order is stable. */
export function orderCards(cards: CardRow[]): CardRow[] {
  return [...cards].sort(
    (a, b) =>
      (ORDER_GROUP[a.kind] ?? LAST_GROUP) - (ORDER_GROUP[b.kind] ?? LAST_GROUP) ||
      effectiveDue(a) - effectiveDue(b) ||
      a.id.localeCompare(b.id),
  );
}

/**
 * The cards a session shows, in order, each with whether it was due when the session began. Due shows today's capped
 * set (`limit` cards a day, null for no cap); more shows the next batch of due cards the cap left waiting. Shuffle
 * takes up to 10 random reviewable cards in random order (`random` is injectable for tests); missed takes the Missed
 * list, worst first. Like an ahead review, both record each card as due or not by its own due date.
 */
export function buildSession(
  data: ReviewData,
  mode: SessionMode,
  id: string | null,
  now: Date,
  limit: number | null,
  random: () => number = Math.random,
): SessionCard[] {
  if (mode === "quiz") {
    return data.cards
      .filter((card) => isOpenQuiz(card, now))
      .sort((a, b) => Date.parse(a.createdAt) - Date.parse(b.createdAt))
      .map((card) => ({ card, wasDue: true }));
  }

  if (mode === "due") return asSession(orderCards(dailyPlan(data, limit, now).today), now);
  if (mode === "more") return asSession(orderCards(moreCards(data, limit, now)), now);

  const reviewable = data.cards.filter((card) => isReviewable(card, data, now));
  if (mode === "shuffle") return asSession(shufflePick(reviewable, SHUFFLE_COUNT, random), now);
  if (mode === "missed") return asSession(missedCards(data, now).map(({ card }) => card), now);

  const aheadLimit = now.getTime() + AHEAD_DAYS * DAY_MS;
  const chosen = reviewable.filter((card) => {
    switch (mode) {
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
  return asSession(orderCards(chosen), now);
}

function asSession(cards: CardRow[], now: Date): SessionCard[] {
  return cards.map((card) => ({ card, wasDue: isDue(card, now) }));
}
