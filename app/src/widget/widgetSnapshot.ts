/**
 * The JSON snapshot the lock-screen widget reads: one ring per Today task for today and tomorrow. Pure; the widget
 * can't run JS or read the database, so the app publishes this (see publish.ts).
 */

import { DAILY_NOTES } from "@/notes/refresher";
import { localDate } from "@/today/todayLabels";
import type { TodayTasks, TomorrowCounts } from "@/today/todayTasks";

export const SNAPSHOT_VERSION = 1;

/** `progress` is 0..1; the widget swaps the symbol for a checkmark when `done`. */
export type WidgetRing = { progress: number; done: boolean };

/** A ring is null when the task has nothing that day. */
export type WidgetDay = {
  day: string;
  rings: { cards: WidgetRing | null; notes: WidgetRing | null; brief: WidgetRing | null };
};

/** `days[0]` is today and `days[1]` tomorrow, by the phone's local date. */
export type WidgetSnapshot = { version: typeof SNAPSHOT_VERSION; days: [WidgetDay, WidgetDay] };

const EMPTY: WidgetRing = { progress: 0, done: false };
const FULL: WidgetRing = { progress: 1, done: true };

export function widgetSnapshot(tasks: TodayTasks, tomorrow: TomorrowCounts, now: Date): WidgetSnapshot {
  const nextDay = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
  return {
    version: SNAPSHOT_VERSION,
    days: [
      { day: localDate(now), rings: todayRings(tasks) },
      {
        day: localDate(nextDay),
        rings: {
          cards: tomorrow.cards > 0 ? EMPTY : null,
          notes: tomorrow.notes > 0 ? EMPTY : null,
          brief: tomorrow.brief ? EMPTY : null,
        },
      },
    ],
  };
}

function todayRings({ review, notes, brief }: TodayTasks): WidgetDay["rings"] {
  return {
    cards: review === null ? null : cardsRing(review),
    notes: notes === null ? null : notesRing(notes),
    brief: brief === null ? null : brief.status === "done" ? FULL : EMPTY,
  };
}

function cardsRing(review: NonNullable<TodayTasks["review"]>): WidgetRing {
  if (review.status === "done") return FULL;
  if (review.status === "pending") return EMPTY;
  return { progress: review.reviewed / review.total, done: false };
}

function notesRing(notes: NonNullable<TodayTasks["notes"]>): WidgetRing {
  if (notes.status === "done") return FULL;
  if (notes.status === "pending") return EMPTY;
  return { progress: (notes.refresher.position - 1) / DAILY_NOTES, done: false };
}
