export type SnoozeChoiceKey = "tonight" | "tomorrow" | "weekend" | "nextWeek";
export type SnoozeChoice = { key: SnoozeChoiceKey; label: string; until: Date };

const TONIGHT_HOUR = 18;
// From 17:00 "Tonight" would be under an hour away, so it isn't offered.
const TONIGHT_CUTOFF_HOUR = 17;
const MORNING_HOUR = 9;
const SATURDAY = 6;
const MONDAY = 1;

function atHour(day: Date, hour: number): Date {
  // Built from local date parts, so DST changes land on the wall-clock hour.
  return new Date(day.getFullYear(), day.getMonth(), day.getDate(), hour, 0, 0, 0);
}

function daysUntil(now: Date, weekday: number): number {
  // Strictly after today: on a Saturday, "this weekend" is next Saturday.
  return (weekday - now.getDay() + 7) % 7 || 7;
}

function plusDays(day: Date, days: number): Date {
  return new Date(day.getFullYear(), day.getMonth(), day.getDate() + days);
}

/** The preset snooze times, in the phone's time zone. */
export function snoozeChoices(now: Date): SnoozeChoice[] {
  const tonight: SnoozeChoice[] =
    now.getHours() < TONIGHT_CUTOFF_HOUR ? [{ key: "tonight", label: "Tonight", until: atHour(now, TONIGHT_HOUR) }] : [];
  return [
    ...tonight,
    { key: "tomorrow", label: "Tomorrow", until: atHour(plusDays(now, 1), MORNING_HOUR) },
    { key: "weekend", label: "This weekend", until: atHour(plusDays(now, daysUntil(now, SATURDAY)), MORNING_HOUR) },
    { key: "nextWeek", label: "Next week", until: atHour(plusDays(now, daysUntil(now, MONDAY)), MORNING_HOUR) },
  ];
}

export function pickedDateUntil(day: Date): Date {
  return atHour(day, MORNING_HOUR);
}

/** "6 PM" today, "Sat 9 AM" within a week, else "Nov 20, 9 AM". */
export function formatReturnTime(until: Date, now: Date): string {
  const hour = until.getHours();
  const time = `${hour % 12 === 0 ? 12 : hour % 12}${until.getMinutes() ? `:${String(until.getMinutes()).padStart(2, "0")}` : ""} ${hour < 12 ? "AM" : "PM"}`;
  const days = Math.round((atHour(until, 0).getTime() - atHour(now, 0).getTime()) / 86_400_000);
  if (days === 0) return time;
  if (days > 0 && days < 7) return `${until.toLocaleDateString("en-US", { weekday: "short" })} ${time}`;
  return `${until.toLocaleDateString("en-US", { month: "short", day: "numeric" })}, ${time}`;
}
