export const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
export const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];
const DAY_MS = 24 * 60 * 60 * 1000;
const WEEKDAY_WINDOW_DAYS = 6;

/** The header date: "Wed · Nov 4". */
export function todayDate(now: Date): string {
  return `${WEEKDAYS[now.getDay()]} · ${MONTHS[now.getMonth()]} ${now.getDate()}`;
}

/** "Mon" within the last 6 days, else "Nov 1". */
export function recentDayLabel(at: string, now: Date): string {
  const date = new Date(at);
  if (now.getTime() - date.getTime() <= WEEKDAY_WINDOW_DAYS * DAY_MS) return WEEKDAYS[date.getDay()];
  return `${MONTHS[date.getMonth()]} ${date.getDate()}`;
}

/** "since Mon" within the last 6 days, else "since Nov 1". */
export function sinceLabel(since: string, now: Date): string {
  return `since ${recentDayLabel(since, now)}`;
}

export function newslettersLine(count: number): string {
  return `${count} ${count === 1 ? "newsletter" : "newsletters"} waiting for your brief`;
}
