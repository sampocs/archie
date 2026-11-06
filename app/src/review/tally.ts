import type { ReviewGrade } from "./types";

export type Tally = { gotIt: number; partly: number; missed: number; dropped: number };
export type TallyEntry = { cardId: string; outcome: ReviewGrade | "dropped" };

const TALLY_KEY = { got_it: "gotIt", partly: "partly", missed: "missed", dropped: "dropped" } as const;

/** Counts each card's last outcome, so "I actually knew it" moves a Partly or Missed to Got it. */
export function tallyOf(entries: TallyEntry[]): Tally {
  const lastByCard = new Map(entries.map((entry) => [entry.cardId, entry.outcome]));
  const tally: Tally = { gotIt: 0, partly: 0, missed: 0, dropped: 0 };
  for (const outcome of lastByCard.values()) tally[TALLY_KEY[outcome]] += 1;
  return tally;
}

/** The cards that got a grade (dropped ones are their own row). */
export function gradedCount(tally: Tally): number {
  return tally.gotIt + tally.partly + tally.missed;
}
