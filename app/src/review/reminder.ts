import type { ReviewSettings } from "@/db/reviewSettings";

import { REMINDER_DAYS } from "./constants";
import { isReviewable, type ReviewData } from "./eligibility";
import { cardsWord } from "./labels";
import { effectiveDue } from "./session";
import { minutesFor } from "./summary";

export type PlannedReminder = { at: Date; count: number; body: string };

/**
 * One reminder a day for the next REMINDER_DAYS days at the reminder time, each only when cards will be due by then.
 * The counts assume no reviews in between; the plan is rebuilt on every foreground and after every session.
 */
export function reminderPlan(data: ReviewData, settings: ReviewSettings, now: Date): PlannedReminder[] {
  if (!settings.reminderEnabled) return [];
  const reviewable = data.cards.filter((card) => isReviewable(card, data));

  return Array.from({ length: REMINDER_DAYS }, (_, offset) => reminderTime(now, offset, settings.reminderMinutes))
    .filter((at) => at.getTime() > now.getTime())
    .map((at) => ({ at, count: reviewable.filter((card) => effectiveDue(card) <= at.getTime()).length }))
    .filter((reminder) => reminder.count > 0)
    .map(({ at, count }) => ({ at, count, body: `${cardsWord(count)} · about ${minutesFor(count)} min` }));
}

function reminderTime(now: Date, dayOffset: number, minutes: number): Date {
  return new Date(now.getFullYear(), now.getMonth(), now.getDate() + dayOffset, Math.floor(minutes / 60), minutes % 60);
}
