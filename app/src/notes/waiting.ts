// The waiting list's model, pure so it is testable without a database; useWaitingBanner reads it live.
import type * as schema from "@/db/schema";

export type WaitingRow = typeof schema.waitingNoteCards.$inferSelect;
export type WaitingSource = Pick<
  typeof schema.sources.$inferSelect,
  "id" | "title" | "url" | "kind" | "deletedAt" | "cardsOff"
>;

/** What Today's banner shows: the oldest waiting note, and how many notes are waiting in all. */
export type WaitingBanner = { sourceId: string; title: string; count: number };

/** The waiting rows that still count: the note exists, is not deleted and has cards on. Oldest waiting first. */
export function liveWaiting(rows: WaitingRow[], sources: WaitingSource[]): WaitingRow[] {
  const liveNotes = new Set(
    sources.filter((source) => source.kind === "note" && source.deletedAt === null && source.cardsOff === 0).map((source) => source.id),
  );

  return rows
    .filter((row) => liveNotes.has(row.sourceId))
    .sort((first, second) => first.waitingAt.localeCompare(second.waitingAt) || first.sourceId.localeCompare(second.sourceId));
}

/** The banner for the waiting list, or null when nothing waits. Its title is the oldest note's. */
export function waitingBanner(rows: WaitingRow[], sources: WaitingSource[]): WaitingBanner | null {
  const live = liveWaiting(rows, sources);
  if (live.length === 0) return null;

  const note = sources.find((source) => source.id === live[0].sourceId)!;
  return { sourceId: note.id, title: note.title ?? note.url, count: live.length };
}
