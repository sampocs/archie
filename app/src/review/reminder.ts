import type { ReviewSettings } from "@/db/reviewSettings";

import { REMINDER_DAYS } from "./constants";
import { reviewedDueToday } from "./dailyCap";
import { effectiveDue } from "./due";
import { isReviewable, type ReviewData } from "./eligibility";
import { cardsWord } from "./labels";
import { minutesFor } from "./summary";

export type PlannedReminder = { at: Date; count: number; body: string };

/**
 * One reminder a day for the next REMINDER_DAYS days at the reminder time, each only when cards will be due by then.
 * The counts assume no reviews in between; the plan is rebuilt on every foreground and after every session. Each count
 * is capped at the daily card limit, today's at what is left of today's.
 */
export function reminderPlan(data: ReviewData, settings: ReviewSettings, now: Date): PlannedReminder[] {
  if (!settings.reminderEnabled) return [];
  // Counted at each reminder's own time, so a card that starts later is in the reminders from its start on.
  const countAt = (at: Date): number =>
    data.cards.filter((card) => isReviewable(card, data, at) && effectiveDue(card) <= at.getTime()).length;
  // Today's reminder is capped at what is left of today's budget; later days at the whole limit.
  const limit = settings.dailyLimit ?? Infinity;
  const todayBudget = Math.max(0, limit - reviewedDueToday(data, data.reviews, now));

  return Array.from({ length: REMINDER_DAYS }, (_, offset) => ({
    at: reminderTime(now, offset, settings.reminderMinutes),
    cap: offset === 0 ? todayBudget : limit,
  }))
    .filter(({ at }) => at.getTime() > now.getTime())
    .map(({ at, cap }) => ({ at, count: Math.min(countAt(at), cap) }))
    .filter((reminder) => reminder.count > 0)
    .map(({ at, count }) => ({ at, count, body: `${cardsWord(count)} · about ${minutesFor(count)} min` }));
}

function reminderTime(now: Date, dayOffset: number, minutes: number): Date {
  return new Date(now.getFullYear(), now.getMonth(), now.getDate() + dayOffset, Math.floor(minutes / 60), minutes % 60);
}
