import { eq } from "drizzle-orm";

import type { AppDb } from "./client";
import * as schema from "./schema";

export type ReviewSettings = { reminderEnabled: boolean; reminderMinutes: number };

// 8:30 PM, as minutes after local midnight.
export const DEFAULT_REVIEW_SETTINGS: ReviewSettings = { reminderEnabled: true, reminderMinutes: 20 * 60 + 30 };

// The single settings row; absent until the user changes anything.
const SETTINGS_ROW_ID = 1;

export function getReviewSettings(db: AppDb): ReviewSettings {
  const row = db.select().from(schema.reviewSettings).where(eq(schema.reviewSettings.id, SETTINGS_ROW_ID)).get();
  if (!row) return DEFAULT_REVIEW_SETTINGS;
  return { reminderEnabled: row.reminderEnabled === 1, reminderMinutes: row.reminderMinutes };
}

export function setReviewSettings(db: AppDb, settings: ReviewSettings): void {
  const values = { reminderEnabled: settings.reminderEnabled ? 1 : 0, reminderMinutes: settings.reminderMinutes };
  db.insert(schema.reviewSettings)
    .values({ id: SETTINGS_ROW_ID, ...values })
    .onConflictDoUpdate({ target: schema.reviewSettings.id, set: values })
    .run();
}
