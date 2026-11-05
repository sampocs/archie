import { todayDate } from "./todayLabels";

// jest.config.js pins TZ to America/New_York.
const now = new Date(2026, 10, 4, 9);

test("todayDate", () => {
  expect(todayDate(now)).toBe("Wed · Nov 4");
});
