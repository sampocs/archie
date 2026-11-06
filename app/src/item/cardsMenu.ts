import type { sources } from "@/db/schema";

type SourceRow = typeof sources.$inferSelect;

/** What the menu's "Make review cards" entry does, or null when it isn't offered. */
export type MakeCardsAction = { kind: "go_deeper" | "cards_on"; subtitle: string };

/** Offered on a ready source whose cards are off or that has none; an inbox item goes through go_deeper. */
export function makeCardsAction(source: SourceRow, cardCount: number): MakeCardsAction | null {
  // Offered only on a ready source, so a re-analysis isn't started on a source that is still processing.
  if (source.processing !== "ready") return null;
  if (source.cardsOff !== 1 && cardCount > 0) return null;

  const inInbox = source.state === "inbox" || source.state === "briefed";
  if (inInbox) return { kind: "go_deeper", subtitle: "Marks it done and writes a primer" };
  return { kind: "cards_on", subtitle: "Writes cards for this again" };
}
