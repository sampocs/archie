import { useEffect } from "react";
import { AppState } from "react-native";

import { db } from "@/db/client";

import { cancelReminders, scheduleReminders } from "./reminderScheduler";

/**
 * Keeps the scheduled reminders in step with the cards: re-planned at launch and whenever the app returns to the
 * foreground (never asking for permission), and cleared on unmount, which is sign-out.
 */
export function ReminderRoot() {
  useEffect(() => {
    void scheduleReminders(db);
    const subscription = AppState.addEventListener("change", (state) => {
      if (state === "active") void scheduleReminders(db);
    });

    return () => {
      subscription.remove();
      void cancelReminders();
    };
  }, []);

  return null;
}
