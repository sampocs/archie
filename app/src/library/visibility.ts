import { CHAT_KIND, READING_STATE } from "@/ui/sourceLabels";

import type { LibrarySource } from "./join";

export type StatusTag =
  | "Queued"
  | "Reading"
  | "Done"
  | "Unread"
  | "Read"
  | "Briefed"
  | "Primer"
  | "Processing"
  | "Failed";

export function isSnoozed(item: { snoozedUntil: string | null }, now: Date): boolean {
  return item.snoozedUntil !== null && new Date(item.snoozedUntil) > now;
}

/** The Library row's tag: the pipeline's state wins while it is working or failed, then the reading state. */
export function statusTag(source: { kind: string; state: string; processing: string; readAt: string | null }): StatusTag {
  if (source.processing === "pending" || source.processing === "processing") return "Processing";
  if (source.processing === "failed") return "Failed";
  if (source.kind === "note" && source.state !== "consumed") return "Read";
  // A chat item is what the owner just worked through in Ask, so it is never unread.
  if (source.kind === CHAT_KIND) return "Read";
  if (source.state === "queued") return "Queued";
  if (source.state === READING_STATE) return "Reading";
  if (source.state === "consumed") return "Done";
  if (source.state === "briefed") return "Briefed";
  return source.readAt ? "Read" : "Unread";
}

/** One row of the queue: a queued source, or a source's primer queued as its own entry. */
export type QueueEntry = { kind: "source" | "primer"; key: string; position: number | null; source: LibrarySource };

/** The queue entry's snooze time: a primer entry snoozes apart from its source. */
export function queueEntrySnoozedUntil(entry: QueueEntry): string | null {
  return entry.kind === "source" ? entry.source.snoozedUntil : entry.source.primerSnoozedUntil;
}

/**
 * Queued sources and queued primers in one order (they share a position space): lowest position first;
 * unpositioned ones last, newest first.
 */
export function queueOrder(sources: LibrarySource[]): QueueEntry[] {
  const sourceEntries: QueueEntry[] = sources
    .filter((source) => source.state === "queued")
    .map((source) => ({ kind: "source", key: `source-${source.id}`, position: source.queuePosition, source }));
  const primerEntries: QueueEntry[] = sources
    .filter((source) => source.primerQueuePosition !== null)
    .map((source) => ({ kind: "primer", key: `primer-${source.id}`, position: source.primerQueuePosition, source }));

  return [...sourceEntries, ...primerEntries].sort((first, second) => {
    const a = first.position ?? Number.POSITIVE_INFINITY;
    const b = second.position ?? Number.POSITIVE_INFINITY;
    return a !== b ? a - b : second.source.createdAt.localeCompare(first.source.createdAt);
  });
}

/** The queue without its snoozed entries: Today's Up next and the Library's draggable queue. */
export function upNext(sources: LibrarySource[], now: Date): QueueEntry[] {
  return queueOrder(sources).filter((entry) => !isSnoozed({ snoozedUntil: queueEntrySnoozedUntil(entry) }, now));
}
