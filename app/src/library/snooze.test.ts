import { formatReturnTime, pickedDateUntil, snoozeChoices } from "./snooze";

// jest.config.js pins TZ to America/New_York; 2026-11-01 is the fall-back DST change.
const local = (year: number, month: number, day: number, hour: number, minute = 0) =>
  new Date(year, month - 1, day, hour, minute);

const choice = (now: Date, key: string) => snoozeChoices(now).find((item) => item.key === key)?.until.toISOString();

describe("snoozeChoices", () => {
  const wednesday = local(2026, 11, 4, 16, 59);

  it("offers Tonight at 18:00 before 17:00", () => {
    const first = snoozeChoices(wednesday)[0];
    expect(first.key).toBe("tonight");
    expect(first.until.toISOString()).toBe("2026-11-04T23:00:00.000Z");
  });

  it("drops Tonight from 17:00", () => {
    expect(snoozeChoices(local(2026, 11, 4, 17)).map((item) => item.key)).toEqual(["tomorrow", "weekend", "nextWeek"]);
  });

  it("puts Tomorrow, This weekend and Next week at 09:00 local", () => {
    expect(choice(wednesday, "tomorrow")).toBe(local(2026, 11, 5, 9).toISOString());
    expect(choice(wednesday, "weekend")).toBe(local(2026, 11, 7, 9).toISOString());
    expect(choice(wednesday, "nextWeek")).toBe(local(2026, 11, 9, 9).toISOString());
  });

  it("keeps 09:00 on the wall clock across the DST change", () => {
    expect(choice(local(2026, 10, 31, 20), "tomorrow")).toBe("2026-11-01T14:00:00.000Z");
  });

  it("means next Saturday by This weekend on a Saturday", () => {
    expect(choice(local(2026, 11, 7, 10), "weekend")).toBe(local(2026, 11, 14, 9).toISOString());
  });
});

describe("pickedDateUntil", () => {
  it("is 09:00 local on the picked day", () => {
    expect(pickedDateUntil(local(2026, 11, 20, 15, 30))).toEqual(local(2026, 11, 20, 9));
  });
});

describe("formatReturnTime", () => {
  const now = local(2026, 11, 4, 10);

  it("gives only the time today", () => {
    expect(formatReturnTime(local(2026, 11, 4, 18), now)).toBe("6 PM");
  });

  it("gives the weekday within a week", () => {
    expect(formatReturnTime(local(2026, 11, 7, 9), now)).toBe("Sat 9 AM");
  });

  it("gives the date further out", () => {
    expect(formatReturnTime(local(2026, 11, 20, 9), now)).toBe("Nov 20, 9 AM");
  });
});
