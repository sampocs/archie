import { isLiveTopic, type LibraryData, type LibrarySource, type TopicPrimerRow, type TopicRow } from "./join";
import { isSnoozed } from "./visibility";

export type LibraryFilter = "all" | "queued" | "done" | "inbox" | "primers";

export const LIBRARY_FILTERS: LibraryFilter[] = ["all", "queued", "done", "inbox", "primers"];

export type LibraryEntry =
  | { kind: "source"; source: LibrarySource }
  | { kind: "topicPrimer"; primer: TopicPrimerRow; topic: TopicRow };

export type WeekSections = { thisWeek: LibraryEntry[]; earlier: LibraryEntry[]; snoozed: LibraryEntry[] };

const WEEK_MS = 7 * 86_400_000;

export function isLibraryFilter(value: unknown): value is LibraryFilter {
  return LIBRARY_FILTERS.includes(value as LibraryFilter);
}

export function entryKey(entry: LibraryEntry): string {
  return entry.kind === "source" ? `source-${entry.source.id}` : `topic-primer-${entry.primer.id}`;
}

export function entryCreatedAt(entry: LibraryEntry): string {
  return entry.kind === "source" ? entry.source.createdAt : entry.primer.createdAt;
}

export function entrySnoozedUntil(entry: LibraryEntry): string | null {
  return entry.kind === "source" ? entry.source.snoozedUntil : entry.primer.snoozedUntil;
}

/** The entries a filter shows, snoozed ones included (Decision 12); topic primers of removed or merged topics never show. */
export function filterEntries(data: LibraryData, filter: LibraryFilter): LibraryEntry[] {
  const sources = (keep: (source: LibrarySource) => boolean): LibraryEntry[] =>
    data.sources.filter(keep).map((source) => ({ kind: "source", source }));

  if (filter === "queued") return sources((source) => source.state === "queued");
  if (filter === "done") return sources((source) => source.state === "consumed");
  if (filter === "inbox") return sources((source) => source.state === "inbox" || source.state === "briefed");
  if (filter === "primers") {
    return [...sources((source) => source.prepMe === 1 && source.primerCreatedAt !== null), ...topicPrimerEntries(data)];
  }
  return [...sources(() => true), ...topicPrimerEntries(data)];
}

/** How many entries each filter shows outside its Snoozed section. */
export function filterCounts(data: LibraryData, now: Date): Record<LibraryFilter, number> {
  const visible = (filter: LibraryFilter): number =>
    filterEntries(data, filter).filter((entry) => !isSnoozed({ snoozedUntil: entrySnoozedUntil(entry) }, now)).length;
  return {
    all: visible("all"),
    queued: visible("queued"),
    done: visible("done"),
    inbox: visible("inbox"),
    primers: visible("primers"),
  };
}

/** Splits entries into created in the last 7 days, older, and snoozed; newest first within each. */
export function byWeek(entries: LibraryEntry[], now: Date): WeekSections {
  const newestFirst = [...entries].sort((first, second) => entryCreatedAt(second).localeCompare(entryCreatedAt(first)));
  const snoozed = newestFirst.filter((entry) => isSnoozed({ snoozedUntil: entrySnoozedUntil(entry) }, now));
  const visible = newestFirst.filter((entry) => !snoozed.includes(entry));
  const isThisWeek = (entry: LibraryEntry): boolean =>
    now.getTime() - new Date(entryCreatedAt(entry)).getTime() <= WEEK_MS;

  return {
    thisWeek: visible.filter(isThisWeek),
    earlier: visible.filter((entry) => !isThisWeek(entry)),
    snoozed,
  };
}

function topicPrimerEntries(data: LibraryData): LibraryEntry[] {
  const topicsById = new Map(data.topics.map((topic) => [topic.id, topic]));
  return data.topicPrimers.flatMap((primer) => {
    const topic = topicsById.get(primer.topicId);
    if (!topic || !isLiveTopic(topic) || primer.isCurrent !== 1) return [];
    return [{ kind: "topicPrimer" as const, primer, topic }];
  });
}
