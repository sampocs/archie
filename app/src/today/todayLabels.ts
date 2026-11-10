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

/** Whether an instant falls on the same calendar day as `now` on this phone. */
export function sameLocalDay(iso: string, now: Date): boolean {
  const date = new Date(iso);
  return (
    date.getFullYear() === now.getFullYear() && date.getMonth() === now.getMonth() && date.getDate() === now.getDate()
  );
}

/** The phone's local date "YYYY-MM-DD". */
export function localDate(day: Date): string {
  const pad = (value: number): string => String(value).padStart(2, "0");
  return `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`;
}
