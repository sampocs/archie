import type { sources } from "@/db/schema";
import { BOOK_KIND, CHAT_KIND } from "@/ui/sourceLabels";

type SourceRow = typeof sources.$inferSelect;

/** Which queue-related entries the ••• menu offers for a source. */
export type QueueEntries = { snooze: boolean; queuePrimer: boolean };

/**
 * A note is read in Today's refresher and a chat item is a reference, so neither is queued or snoozed. A book is
 * never queued itself, so it can't be snoozed, and the server writes no primer on demand for one: its primer can
 * be queued only once it exists.
 */
export function queueEntries(source: Pick<SourceRow, "kind">, primerWords: number | null): QueueEntries {
  const queueable = source.kind !== "note" && source.kind !== CHAT_KIND;
  const isBook = source.kind === BOOK_KIND;
  return { snooze: queueable && !isBook, queuePrimer: queueable && (!isBook || primerWords !== null) };
}
