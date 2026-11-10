/** What Today has already celebrated on this phone today, so each finish animates once per local day. */

import type { TaskKind } from "./todayTasks";

export const DAY_DONE = "day";
export type CelebrationKey = TaskKind | typeof DAY_DONE;

type StoredCelebrations = { day: string; keys: CelebrationKey[] };

/** The keys celebrated on `day`, from the stored value; anything stored for an earlier day counts for nothing. */
export function celebratedOn(stored: string | null, day: string): Set<CelebrationKey> {
  if (stored === null) return new Set();
  const parsed = JSON.parse(stored) as StoredCelebrations;
  return parsed.day === day ? new Set(parsed.keys) : new Set();
}

/** The value to store once `keys` have been celebrated on `day`. */
export function storedCelebrations(day: string, keys: Iterable<CelebrationKey>): string {
  const stored: StoredCelebrations = { day, keys: [...new Set(keys)] };
  return JSON.stringify(stored);
}
