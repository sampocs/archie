import type { sources } from "@/db/schema";
import { BOOK_KIND, CHAT_KIND, READING_STATE } from "@/ui/sourceLabels";

type SourceRow = typeof sources.$inferSelect;

/** What the menu's "Make review cards" entry does, or null when it isn't offered. */
export type MakeCardsAction = { kind: "go_deeper" | "cards_on"; subtitle: string };

const CARDS_ON: MakeCardsAction = { kind: "cards_on", subtitle: "Writes cards for this again" };

/**
 * Offered on a ready source whose cards are off or that has none; an inbox item goes through go_deeper.
 * A note only ever flips cards_off (its write-up already exists), so it is offered just when cards are off. A chat
 * item's cards come only from Save in its chat, so it is never offered. A reading book is never offered it either:
 * the server only flips the flag there, and its cards are written when it is finished.
 */
export function makeCardsAction(
  source: Pick<SourceRow, "kind" | "processing" | "cardsOff" | "state">,
  cardCount: number,
): MakeCardsAction | null {
  // Offered only on a ready source, so a re-analysis isn't started on a source that is still processing.
  if (source.processing !== "ready") return null;
  if (source.kind === CHAT_KIND) return null;
  if (source.kind === BOOK_KIND && source.state === READING_STATE) return null;
  if (source.kind === "note") return source.cardsOff === 1 ? CARDS_ON : null;
  if (source.cardsOff !== 1 && cardCount > 0) return null;

  const inInbox = source.state === "inbox" || source.state === "briefed";
  if (inInbox) return { kind: "go_deeper", subtitle: "Marks it done and writes a primer" };
  return CARDS_ON;
}
