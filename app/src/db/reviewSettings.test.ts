import { eq } from "drizzle-orm";

import { DEFAULT_REVIEW_SETTINGS, getReviewSettings, setReviewSettings } from "./reviewSettings";
import * as schema from "./schema";
import { makeTestDb } from "./testDb";

describe("review settings", () => {
  it("reads the defaults until anything is saved", () => {
    expect(getReviewSettings(makeTestDb())).toEqual({
      reminderEnabled: true,
      reminderMinutes: 20 * 60 + 30,
      dailyLimit: 20,
    });
  });

  it("reads back what was saved, and a second save replaces it", () => {
    const db = makeTestDb();

    setReviewSettings(db, { reminderEnabled: false, reminderMinutes: 7 * 60, dailyLimit: 20 });
    expect(getReviewSettings(db)).toEqual({ reminderEnabled: false, reminderMinutes: 7 * 60, dailyLimit: 20 });

    setReviewSettings(db, { ...DEFAULT_REVIEW_SETTINGS, reminderMinutes: 21 * 60 });
    expect(getReviewSettings(db)).toEqual({ reminderEnabled: true, reminderMinutes: 21 * 60, dailyLimit: 20 });
  });

  it("keeps a cap of Off as Off, and reads a row saved before the cap existed as the default", () => {
    const db = makeTestDb();

    setReviewSettings(db, { ...DEFAULT_REVIEW_SETTINGS, dailyLimit: null });
    expect(getReviewSettings(db).dailyLimit).toBeNull();

    db.update(schema.reviewSettings).set({ dailyLimit: null }).where(eq(schema.reviewSettings.id, 1)).run();
    expect(getReviewSettings(db).dailyLimit).toBe(20);
  });
});
