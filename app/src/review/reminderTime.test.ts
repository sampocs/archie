import { dateToMinutes, formatReminderTime, minutesToDate } from "./reminderTime";

describe("reminder time", () => {
  it("formats minutes after midnight as local clock text", () => {
    expect(formatReminderTime(20 * 60 + 30)).toBe("8:30 PM");
    expect(formatReminderTime(7 * 60 + 5)).toBe("7:05 AM");
  });

  it("round-trips through the picker's date", () => {
    expect(dateToMinutes(minutesToDate(20 * 60 + 30))).toBe(20 * 60 + 30);
  });
});
