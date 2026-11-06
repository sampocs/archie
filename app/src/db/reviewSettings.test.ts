import { DEFAULT_REVIEW_SETTINGS, getReviewSettings, setReviewSettings } from "./reviewSettings";
import { makeTestDb } from "./testDb";

describe("review settings", () => {
  it("reads the defaults until anything is saved", () => {
    expect(getReviewSettings(makeTestDb())).toEqual({ reminderEnabled: true, reminderMinutes: 20 * 60 + 30 });
  });

  it("reads back what was saved, and a second save replaces it", () => {
    const db = makeTestDb();

    setReviewSettings(db, { reminderEnabled: false, reminderMinutes: 7 * 60 });
    expect(getReviewSettings(db)).toEqual({ reminderEnabled: false, reminderMinutes: 7 * 60 });

    setReviewSettings(db, { ...DEFAULT_REVIEW_SETTINGS, reminderMinutes: 21 * 60 });
    expect(getReviewSettings(db)).toEqual({ reminderEnabled: true, reminderMinutes: 21 * 60 });
  });
});
