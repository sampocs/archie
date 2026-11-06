/** The reminder time as local clock text ("8:30 PM"); the time is stored as minutes after local midnight. */
export function formatReminderTime(minutes: number): string {
  return minutesToDate(minutes).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
}

/** Today at the given minutes after midnight, the value the time picker works in. */
export function minutesToDate(minutes: number): Date {
  const date = new Date();
  date.setHours(Math.floor(minutes / 60), minutes % 60, 0, 0);
  return date;
}

export function dateToMinutes(date: Date): number {
  return date.getHours() * 60 + date.getMinutes();
}
