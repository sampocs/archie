import type { LibrarySource } from "./join";

export type StatusTag = "Queued" | "Done" | "Unread" | "Read" | "Briefed" | "Primer" | "Processing" | "Failed";

export function isSnoozed(item: { snoozedUntil: string | null }, now: Date): boolean {
  return item.snoozedUntil !== null && new Date(item.snoozedUntil) > now;
}

/** The Library row's tag: the pipeline's state wins while it is working or failed, then the reading state. */
export function statusTag(source: { state: string; processing: string; readAt: string | null }): StatusTag {
  if (source.processing === "pending" || source.processing === "processing") return "Processing";
  if (source.processing === "failed") return "Failed";
  if (source.state === "queued") return "Queued";
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

export type WaitingNewsletters = { count: number; senders: string[]; since: string | null };

/** Newsletters in the inbox (not briefed, not snoozed): how many, the two newest distinct senders, the oldest time. */
export function waitingNewsletters(sources: LibrarySource[], now: Date): WaitingNewsletters {
  const waiting = sources
    .filter((source) => source.kind === "newsletter" && source.state === "inbox" && !isSnoozed(source, now))
    .sort((first, second) => second.createdAt.localeCompare(first.createdAt));
  const senders = [...new Set(waiting.map((source) => source.sender ?? "Newsletter"))].slice(0, 2);
  return { count: waiting.length, senders, since: waiting.at(-1)?.createdAt ?? null };
}
