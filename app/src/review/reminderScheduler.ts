import * as Notifications from "expo-notifications";

import type { AppDb } from "@/db/client";
import { getReviewSettings } from "@/db/reviewSettings";

import { reminderPlan } from "./reminder";
import { readReviewData } from "./useReviewData";

const REMINDER_TITLE = "Time to review";

// Every reminder call runs on this chain, one at a time. Overlapping calls (a spinner change, the permission dialog's
// inactive -> active flip, a sign-out cancel) would otherwise both cancel and then both schedule, duplicating
// reminders or leaving a stale time. The chain never rejects: each task catches its own errors.
let queue: Promise<void> = Promise.resolve();

function enqueue(task: () => Promise<void>): Promise<void> {
  queue = queue.then(task);
  return queue;
}

/**
 * Replaces the scheduled reminders with the current plan. Asks for notification permission only when `askPermission`
 * (after a finished session or turning reminders on), never at launch. Calls are serialized: each starts after the
 * previous one (or a `cancelReminders`) has finished.
 */
export function scheduleReminders(db: AppDb, options: { askPermission?: boolean } = {}): Promise<void> {
  return enqueue(async () => {
    try {
      // Reminders off: clear what's scheduled without ever asking for permission.
      const settings = getReviewSettings(db);
      if (!settings.reminderEnabled) {
        await Notifications.cancelAllScheduledNotificationsAsync();
        return;
      }
      if (!(await hasPermission(options.askPermission ?? false))) return;

      const plan = reminderPlan(readReviewData(db), settings, new Date());

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
  });
}

/** Cancels every scheduled reminder (sign-out, or reminders turned off), after any call already running. */
export function cancelReminders(): Promise<void> {
  return enqueue(async () => {
    try {
      await Notifications.cancelAllScheduledNotificationsAsync();
    } catch {
      // As above: reminders are best-effort and must never break the caller.
    }
  });
}

async function hasPermission(askPermission: boolean): Promise<boolean> {
  const current = await Notifications.getPermissionsAsync();
  if (current.granted || !askPermission) return current.granted;
  return (await Notifications.requestPermissionsAsync()).granted;
}
