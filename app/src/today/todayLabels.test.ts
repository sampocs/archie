import { newslettersLine, sinceLabel, todayDate } from "./todayLabels";

// jest.config.js pins TZ to America/New_York.
const now = new Date(2026, 10, 4, 9);

test("todayDate", () => {
  expect(todayDate(now)).toBe("Wed · Nov 4");
});

test("sinceLabel uses the weekday within six days, else the date", () => {
  expect(sinceLabel(new Date(2026, 10, 2, 8).toISOString(), now)).toBe(
    "since Mon",
  );
  expect(sinceLabel(new Date(2026, 9, 25, 8).toISOString(), now)).toBe(
    "since Oct 25",
  );
});

test("newslettersLine pluralizes", () => {
  expect(newslettersLine(1)).toBe("1 newsletter waiting for your brief");
  expect(newslettersLine(6)).toBe("6 newsletters waiting for your brief");
});
