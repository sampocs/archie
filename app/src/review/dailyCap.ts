/**
 * The daily card cap: which due cards a day's "due" session shows, and which wait. Nothing is rescheduled; a card left
 * out stays due and is simply more overdue tomorrow, which barely matters to FSRS.
 */

import { sameLocalDay } from "@/today/todayLabels";

import { effectiveDue, isDue } from "./due";
import { isReviewable, type ReviewData, type ReviewLogRow } from "./eligibility";
import type { CardRow } from "./types";

export const DEFAULT_DAILY_LIMIT = 20;
// New cards get these slots first, so new material never stalls behind a review backlog.
export const NEW_CARD_SLOTS = 5;
export const DAILY_LIMIT_STEPS = [10, 15, 20, 25, 30, 35, 40, 45, 50] as const;

const QUIZ_KIND = "quiz";

// `budget` is what today still has room for; null when there is no cap.
export type DailyPlan = { today: CardRow[]; waiting: CardRow[]; budget: number | null };

/** Today's capped set and the due cards left waiting; limit null = no cap. */
export function dailyPlan(data: ReviewData, limit: number | null, now: Date): DailyPlan {
  const due = data.cards.filter((card) => isReviewable(card, data, now) && isDue(card, now));
  if (limit === null) return { today: due, waiting: [], budget: null };

  const budget = Math.max(0, limit - reviewedDueToday(data, data.reviews, now));
  const { picked, rest } = pickCards(due, budget);
  return { today: picked, waiting: rest, budget };
}

/**
 * The setting one step up or down: 10, 15 … 50, then Off (null). Null when there is no step that way (− at 10, + at
 * Off).
 */
export function stepDailyLimit(limit: number | null, step: 1 | -1): { value: number | null } | null {
  const values: (number | null)[] = [...DAILY_LIMIT_STEPS, null];
  const index = values.indexOf(limit);
  const nextIndex = (index === -1 ? values.indexOf(DEFAULT_DAILY_LIMIT) : index) + step;
  return nextIndex >= 0 && nextIndex < values.length ? { value: values[nextIndex] } : null;
}

/** The next batch of waiting cards a "Keep going" session shows: up to `limit` of them, picked as today's set is. */
export function moreCards(data: ReviewData, limit: number | null, now: Date): CardRow[] {
  const { waiting } = dailyPlan(data, limit, now);
  return pickCards(waiting, limit ?? waiting.length).picked;
}

/**
 * Distinct non-quiz cards reviewed today that were due when reviewed, so a re-graded answer ("I actually knew it") or
 * a missed card seen twice counts once; quiz answers belong to the quiz.
 */
export function reviewedDueToday(reviewData: ReviewData, reviews: ReviewLogRow[], now: Date): number {
  const quizCards = new Set(reviewData.cards.filter((card) => card.kind === QUIZ_KIND).map((card) => card.id));
  const cardIds = reviews
    .filter((review) => review.wasDue === 1 && sameLocalDay(review.reviewedAt, now) && !quizCards.has(review.cardId))
    .map((review) => review.cardId);
  return new Set(cardIds).size;
}

// Reviews earliest due first; new cards in arrival order. New cards take their reserved slots, reviews the rest, and
// slots reviews can't fill go back to new cards.
function pickCards(cards: CardRow[], budget: number): { picked: CardRow[]; rest: CardRow[] } {
  const reviews = cards
    .filter((card) => card.fsrsState !== "new")
    .sort((a, b) => effectiveDue(a) - effectiveDue(b) || a.id.localeCompare(b.id));
  const fresh = cards
    .filter((card) => card.fsrsState === "new")
    .sort((a, b) => arrivedAt(a) - arrivedAt(b) || a.id.localeCompare(b.id));

  const newSlots = Math.min(NEW_CARD_SLOTS, fresh.length, budget);
  const reviewSlots = Math.min(reviews.length, budget - newSlots);
  const freshTaken = Math.min(fresh.length, budget - reviewSlots);
  return {
    picked: [...fresh.slice(0, freshTaken), ...reviews.slice(0, reviewSlots)],
    rest: [...fresh.slice(freshTaken), ...reviews.slice(reviewSlots)],
  };
}

function arrivedAt(card: CardRow): number {
  return Date.parse(card.availableAt ?? card.createdAt);
}
