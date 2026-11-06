import * as Notifications from "expo-notifications";

import type { AppDb } from "@/db/client";
import { getReviewSettings } from "@/db/reviewSettings";

import { makeReviewData } from "./eligibility";
import { reminderPlan } from "./reminder";
import { reviewQueries } from "./useReviewData";

const REMINDER_TITLE = "Time to review";

/**
 * Replaces the scheduled reminders with the current plan. Asks for notification permission only when `askPermission`
 * (after a finished session or turning reminders on), never at launch.
 */
export async function scheduleReminders(db: AppDb, options: { askPermission?: boolean } = {}): Promise<void> {
  try {
    // Reminders off: clear what's scheduled without ever asking for permission.
    const settings = getReviewSettings(db);
    if (!settings.reminderEnabled) {
      await Notifications.cancelAllScheduledNotificationsAsync();
      return;
    }
    if (!(await hasPermission(options.askPermission ?? false))) return;

    const queries = reviewQueries(db);
    const data = makeReviewData({
      cards: queries.cards.all(),
      sources: queries.sources.all(),
      topicPrimers: queries.topicPrimers.all(),
      topics: queries.topics.all(),
    });
    const plan = reminderPlan(data, settings, new Date());

    await Notifications.cancelAllScheduledNotificationsAsync();
    for (const { at, body } of plan) {
      await Notifications.scheduleNotificationAsync({
        content: { title: REMINDER_TITLE, body },
        trigger: { type: Notifications.SchedulableTriggerInputTypes.DATE, date: at },
      });
    }
  } catch {
    // A missing permission or a simulator quirk must never break a session; the plan is rebuilt on the next foreground.
  }
}

/** Cancels every scheduled reminder (sign-out, or reminders turned off). */
export async function cancelReminders(): Promise<void> {
  try {
    await Notifications.cancelAllScheduledNotificationsAsync();
  } catch {
    // As above: reminders are best-effort and must never break the caller.
  }
}

async function hasPermission(askPermission: boolean): Promise<boolean> {
  const current = await Notifications.getPermissionsAsync();
  if (current.granted || !askPermission) return current.granted;
  return (await Notifications.requestPermissionsAsync()).granted;
}
