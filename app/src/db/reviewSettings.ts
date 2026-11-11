import { eq } from "drizzle-orm";

import { DEFAULT_DAILY_LIMIT } from "@/review/dailyCap";

import type { AppDb } from "./client";
import * as schema from "./schema";

// `dailyLimit` is cards per day; null means no cap.
export type ReviewSettings = { reminderEnabled: boolean; reminderMinutes: number; dailyLimit: number | null };

// 8:30 PM, as minutes after local midnight.
export const DEFAULT_REVIEW_SETTINGS: ReviewSettings = {
  reminderEnabled: true,
  reminderMinutes: 20 * 60 + 30,
  dailyLimit: DEFAULT_DAILY_LIMIT,
};

// The single settings row; absent until the user changes anything.
const SETTINGS_ROW_ID = 1;
// Off is stored as 0, since NULL is what a row saved before the cap existed holds, and that must read as the default.
const LIMIT_OFF = 0;

type SettingsRow = typeof schema.reviewSettings.$inferSelect;

export function getReviewSettings(db: AppDb): ReviewSettings {
  const row = db.select().from(schema.reviewSettings).where(eq(schema.reviewSettings.id, SETTINGS_ROW_ID)).get();
  return reviewSettingsOf(row);
}

/** The settings a stored row holds; no row is the defaults. */
export function reviewSettingsOf(row: SettingsRow | undefined): ReviewSettings {
  if (!row) return DEFAULT_REVIEW_SETTINGS;
  const dailyLimit =
    row.dailyLimit === null ? DEFAULT_DAILY_LIMIT : row.dailyLimit === LIMIT_OFF ? null : row.dailyLimit;
  return { reminderEnabled: row.reminderEnabled === 1, reminderMinutes: row.reminderMinutes, dailyLimit };
}

export function setReviewSettings(db: AppDb, settings: ReviewSettings): void {
  const values = {
    reminderEnabled: settings.reminderEnabled ? 1 : 0,
    reminderMinutes: settings.reminderMinutes,
    dailyLimit: settings.dailyLimit ?? LIMIT_OFF,
  };
  db.insert(schema.reviewSettings)
    .values({ id: SETTINGS_ROW_ID, ...values })
    .onConflictDoUpdate({ target: schema.reviewSettings.id, set: values })
    .run();
}
