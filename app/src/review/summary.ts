import { WEEKDAYS } from "@/today/todayLabels";
import { shortDate } from "@/ui/sourceLabels";

import { AHEAD_DAYS, SECONDS_PER_CARD } from "./constants";
import { effectiveDue, isDue } from "./due";
import { isAvailable, isReviewable, type ReviewData } from "./eligibility";
import { cardsWord } from "./labels";
import { buildSession } from "./session";
import type { CardRow } from "./types";

const DAY_MS = 86_400_000;
// Past tomorrow, a day this close is named by its weekday; further out by its date or a day count.
const WEEKDAY_WINDOW_DAYS = 6;

/** The time estimate for a session of `count` cards, in whole minutes (at least 1). */
export function minutesFor(count: number): number {
  return Math.max(1, Math.ceil((count * SECONDS_PER_CARD) / 60));
}

/** The due session's length. */
export function dueSummary(data: ReviewData, now: Date): { count: number } {
  return { count: buildSession(data, "due", null, now).length };
}

/** The ahead session's length, and when its window ends. */
export function aheadSummary(data: ReviewData, now: Date): { count: number; by: Date } {
  return {
    count: buildSession(data, "ahead", null, now).length,
    by: new Date(now.getTime() + AHEAD_DAYS * DAY_MS),
  };
}

/** When cards next come due (the earliest not-due card) and how many come due by the end of that day. */
export function nextReview(data: ReviewData, now: Date): { at: Date; count: number } | null {
  const waiting = data.cards.filter((card) => isReviewable(card, data, now) && !isDue(card, now)).map(effectiveDue);
  if (waiting.length === 0) return null;

  const at = new Date(Math.min(...waiting));
  const dayEnd = addDays(startOfDay(at), 1).getTime();
  return { at, count: waiting.filter((due) => due < dayEnd).length };
}

/** The caught-up card's line: "Next 5 cards are due tomorrow." / "Next card is due Thu." / "… due Nov 14." */
export function nextDueLine(next: { at: Date; count: number }, now: Date): string {
  const when = dayWord(next.at, now, "short");
  return next.count === 1 ? `Next card is due ${when}.` : `Next ${cardsWord(next.count)} are due ${when}.`;
}

/** "today" / "tomorrow" / "Saturday" (or "Sat" with `weekday: "short"`) within 6 days / "Nov 14". */
export function dayWord(day: Date, now: Date, weekday: "long" | "short" = "long"): string {
  const days = daysFrom(now, day);
  if (days === 0) return "today";
  if (days === 1) return "tomorrow";
  if (days > 1 && days <= WEEKDAY_WINDOW_DAYS) {
    return weekday === "short" ? shortWeekday(day) : day.toLocaleDateString("en-US", { weekday: "long" });
  }
  return day.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

/** "Sat". */
export function shortWeekday(day: Date): string {
  return WEEKDAYS[day.getDay()];
}

/** The due wording on an item page's card row; a card that starts later says when ("Starts Nov 24"). */
export function cardDueLabel(card: CardRow, data: ReviewData, now: Date): string {
  if (card.availableAt !== null && !isAvailable(card, now) && isReviewable(card, data, new Date(card.availableAt))) {
    return `Starts ${shortDate(card.availableAt)}`;
  }
  if (!isReviewable(card, data, now)) return "After you finish";

  const due = new Date(effectiveDue(card));
  const days = daysFrom(now, due);
  if (days <= 0) return "Due today";
  if (days === 1) return "Due tomorrow";
  if (days <= WEEKDAY_WINDOW_DAYS) return `Due ${shortWeekday(due)}`;
  return `Due in ${days} days`;
}

function startOfDay(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

function addDays(day: Date, days: number): Date {
  return new Date(day.getFullYear(), day.getMonth(), day.getDate() + days);
}

/** Whole local calendar days from `now` to `day`; rounded, since a DST change makes one day 23 or 25 hours long. */
export function daysFrom(now: Date, day: Date): number {
  return Math.round((startOfDay(day).getTime() - startOfDay(now).getTime()) / DAY_MS);
}
