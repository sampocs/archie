import { isLiveTopic, type LibraryData, type LibrarySource, type TopicPrimerRow, type TopicRow } from "./join";

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

/** Queued sources in queue order: lowest position first; unpositioned ones last, newest first. */
export function queueOrder(sources: LibrarySource[]): LibrarySource[] {
  return sources
    .filter((source) => source.state === "queued")
    .sort((first, second) => {
      const a = first.queuePosition ?? Number.POSITIVE_INFINITY;
      const b = second.queuePosition ?? Number.POSITIVE_INFINITY;
      return a !== b ? a - b : second.createdAt.localeCompare(first.createdAt);
    });
}

export function upNext(sources: LibrarySource[], now: Date): LibrarySource[] {
  return queueOrder(sources).filter((source) => !isSnoozed(source, now));
}

export type PrimerReadyItem =
  | { kind: "source"; key: string; createdAt: string; source: LibrarySource }
  | { kind: "topic"; key: string; createdAt: string; primer: TopicPrimerRow; topic: TopicRow };

/** Pushed primers nobody has opened yet, newest first: prepped sources' primers and live topics' primers. */
export function primersReady(data: LibraryData, now: Date): PrimerReadyItem[] {
  const sourceItems: PrimerReadyItem[] = data.sources
    .filter((source) => source.prepMe === 1 && source.primerCreatedAt && !source.primerOpenedAt && !isSnoozed(source, now))
    .map((source) => ({ kind: "source", key: `source-${source.id}`, createdAt: source.primerCreatedAt!, source }));

  const topicsById = new Map(data.topics.map((topic) => [topic.id, topic]));
  const topicItems: PrimerReadyItem[] = data.topicPrimers.flatMap((primer) => {
    const topic = topicsById.get(primer.topicId);
    if (!topic || !isLiveTopic(topic) || primer.openedAt || isSnoozed(primer, now)) return [];
    return [{ kind: "topic" as const, key: `topic-${primer.id}`, createdAt: primer.createdAt, primer, topic }];
  });

  return [...sourceItems, ...topicItems].sort((first, second) => second.createdAt.localeCompare(first.createdAt));
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
