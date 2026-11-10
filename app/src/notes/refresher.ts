/** The note refresher: which note Today offers next, and how Library labels a note. Pure, so day boundaries are testable. */

import type { LibrarySource } from "@/library/join";
import { readingMinutes, wordCount } from "@/library/primer";
import { recentDayLabel, sameLocalDay } from "@/today/todayLabels";

export const DAILY_NOTES = 2;

const NEXT_UP_COUNT = 2;

export type TodayRefresher =
  | { kind: "pick"; position: number; note: LibrarySource; minutes: number; nextUp: string[] }
  // Done for today: how many came off the queue today, and the note tomorrow starts with.
  | { kind: "done"; refreshed: number; next: LibrarySource | null };

const editedAt = (source: LibrarySource): string => source.noteEditedAt ?? source.createdAt;

const runKey = (source: LibrarySource): string =>
  source.topicId ?? (source.domain ? `domain:${source.domain}` : "none");

const titleOf = (source: LibrarySource): string => source.title ?? source.url;

/** A note waiting in the refresher: a live note with cards on, not refreshed, whose write-up exists. */
export function isRefreshable(source: LibrarySource): boolean {
  return (
    source.kind === "note" &&
    source.deletedAt === null &&
    source.cardsOff === 0 &&
    source.refreshedAt === null &&
    source.summary !== null
  );
}

/** The refresher queue, in order: unskipped notes in topic runs (runs by most recent edit), then skipped ones. */
export function refresherQueue(sources: LibrarySource[]): LibrarySource[] {
  const waiting = sources.filter(isRefreshable);
  const newestFirst = (first: LibrarySource, second: LibrarySource): number =>
    editedAt(second).localeCompare(editedAt(first)) || first.id.localeCompare(second.id);

  // Related notes come back to back: each run keeps its own newest-first order, and since the notes are sorted
  // first, the map's insertion order puts the run with the newest note first.
  const runs = new Map<string, LibrarySource[]>();
  for (const note of waiting.filter((source) => source.refreshSkippedAt === null).sort(newestFirst)) {
    runs.set(runKey(note), [...(runs.get(runKey(note)) ?? []), note]);
  }

  // A skipped note goes to the back whatever its run, so skipping never reshuffles the notes before it.
  const skipped = waiting
    .filter((source) => source.refreshSkippedAt !== null)
    .sort((first, second) => (first.refreshSkippedAt ?? "").localeCompare(second.refreshSkippedAt ?? "") || first.id.localeCompare(second.id));

  return [...[...runs.values()].flat(), ...skipped];
}

/** What Today's refresher card shows, or null for no card. */
export function todayRefresher(sources: LibrarySource[], now: Date): TodayRefresher | null {
  // Only refreshes that came off the queue count toward the day's two; an early one from Library doesn't.
  const counted = sources.filter(
    (source) => source.refreshedFromQueue === 1 && source.refreshedAt !== null && sameLocalDay(source.refreshedAt, now),
  ).length;
  const queue = refresherQueue(sources);

  if (counted >= DAILY_NOTES || (queue.length === 0 && counted > 0)) {
    return { kind: "done", refreshed: counted, next: queue[0] ?? null };
  }
  if (queue.length === 0) return null;

  const [note, ...rest] = queue;
  return {
    kind: "pick",
    position: counted + 1,
    note,
    minutes: readingMinutes(wordCount(writeUpText(note))),
    nextUp: rest.slice(0, NEXT_UP_COUNT).map(titleOf),
  };
}

/** The Library row's meta line for a note. */
export function noteMeta(source: LibrarySource, queue: LibrarySource[], now: Date): string {
  if (source.refreshedAt !== null) {
    const when = sameLocalDay(source.refreshedAt, now) ? "today" : recentDayLabel(source.refreshedAt, now);
    const cards = source.cardCount === 1 ? "1 card" : `${source.cardCount} cards`;
    return `Notes · refreshed ${when}${source.cardCount > 0 ? ` · ${cards}` : ""}`;
  }

  const position = queue.findIndex((queued) => queued.id === source.id);
  if (position === 0) return "Notes · up next";
  if (position > 0) return "Notes · to refresh";
  if (source.cardsOff === 0 && source.summary === null) return "Notes · from Bear";
  return "Notes";
}

/** "5 review cards added from Liquid Staking". */
export function cardsAddedMessage(count: number, title: string): string {
  return `${count} review ${count === 1 ? "card" : "cards"} added from ${title}`;
}

function writeUpText(source: LibrarySource): string {
  const summary = source.summary;
  if (summary === null) return "";
  return [summary.gist, ...summary.key_ideas.map((item) => item.idea), ...summary.numbers.map((item) => item.fact)].join(" ");
}
