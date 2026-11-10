import type * as schema from "@/db/schema";
import { WEEKDAYS } from "@/today/todayLabels";

import { AHEAD_DAYS, SECONDS_PER_CARD } from "./constants";
import { cardTopicId, isReviewable, type ReviewData } from "./eligibility";
import { buildSession, effectiveDue, isDue } from "./session";
import type { CardRow } from "./types";

type TopicRow = typeof schema.topics.$inferSelect;

const DAY_MS = 86_400_000;
// Past tomorrow, a day this close is named by its weekday; further out by its date or a day count.
const WEEKDAY_WINDOW_DAYS = 6;

/** The time estimate for a session of `count` cards, in whole minutes (at least 1). */
export function minutesFor(count: number): number {
  return Math.max(1, Math.ceil((count * SECONDS_PER_CARD) / 60));
}

/** The due session's length, and how many of its cards are foundations. */
export function dueSummary(data: ReviewData, now: Date): { count: number; foundations: number } {
  const session = buildSession(data, "due", null, now);
  return { count: session.length, foundations: session.filter(({ card }) => card.kind === "foundation").length };
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
  const waiting = data.cards.filter((card) => isReviewable(card, data) && !isDue(card, now)).map(effectiveDue);
  if (waiting.length === 0) return null;

  const at = new Date(Math.min(...waiting));
  const dayEnd = addDays(startOfDay(at), 1).getTime();
  return { at, count: waiting.filter((due) => due < dayEnd).length };
}

/** "today" / "tomorrow" / "Saturday" within 6 days / "Nov 14". */
export function dayWord(day: Date, now: Date): string {
  const days = daysFrom(now, day);
  if (days === 0) return "today";
  if (days === 1) return "tomorrow";
  if (days > 1 && days <= WEEKDAY_WINDOW_DAYS) return day.toLocaleDateString("en-US", { weekday: "long" });
  return day.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

/** "Sat". */
export function shortWeekday(day: Date): string {
  return WEEKDAYS[day.getDay()];
}

/** The due wording on an item page's card row. */
export function cardDueLabel(card: CardRow, data: ReviewData, now: Date): string {
  if (!isReviewable(card, data)) return "After you finish";

  const due = new Date(effectiveDue(card));
  const days = daysFrom(now, due);
  if (days <= 0) return "Due today";
  if (days === 1) return "Due tomorrow";
  if (days <= WEEKDAY_WINDOW_DAYS) return `Due ${shortWeekday(due)}`;
  return `Due in ${days} days`;
}

/** Each live topic with reviewable cards and how many it has: busiest first, then by name. */
export function topicPractice(data: ReviewData): { topic: TopicRow; count: number }[] {
  const countByTopic = new Map<string, number>();
  for (const card of data.cards) {
    const topicId = cardTopicId(card, data);
    if (topicId === null || !isReviewable(card, data)) continue;
    countByTopic.set(topicId, (countByTopic.get(topicId) ?? 0) + 1);
  }

  return [...data.topicsById.values()]
    .filter((topic) => topic.removedAt === null && topic.mergedIntoId === null)
    .map((topic) => ({ topic, count: countByTopic.get(topic.id) ?? 0 }))
    .filter(({ count }) => count > 0)
    .sort((a, b) => b.count - a.count || a.topic.name.localeCompare(b.topic.name));
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
