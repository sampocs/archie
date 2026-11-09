import type { LibraryData } from "./join";
import { byWeek, entryKey, filterCounts, filterEntries, type LibraryEntry, type LibraryFilter } from "./sections";
import { noteSource, sourceRow, topicPrimerRow, topicRow } from "./testRows";

const NOW = new Date("2026-11-04T15:00:00Z");
const FUTURE = "2026-11-05T14:00:00Z";
const PAST = "2026-11-04T14:00:00Z";

const data: LibraryData = {
  confirmations: [],
  pendingSenders: [],
  sources: [
    sourceRow({ id: "queued", state: "queued" }),
    sourceRow({ id: "queued-snoozed", state: "queued", snoozedUntil: FUTURE }),
    sourceRow({ id: "queued-woke", state: "queued", snoozedUntil: PAST }),
    sourceRow({ id: "done", state: "consumed" }),
    sourceRow({ id: "inbox", state: "inbox", kind: "newsletter" }),
    sourceRow({ id: "briefed", state: "briefed", kind: "newsletter" }),
    noteSource({ id: "note", state: "inbox" }),
    sourceRow({ id: "chat", kind: "chat", state: "inbox", primerCreatedAt: PAST }),
    sourceRow({ id: "queued-with-primer", state: "queued", primerCreatedAt: PAST }),
    sourceRow({ id: "done-with-primer", state: "consumed", primerCreatedAt: PAST, primerQueuePosition: -1 }),
    sourceRow({ id: "primer-writing", state: "consumed", primerQueuePosition: -2 }),
    sourceRow({ id: "primer-snoozed", state: "consumed", primerQueuePosition: -3, primerSnoozedUntil: FUTURE }),
  ],
  topics: [
    topicRow({ id: "live" }),
    topicRow({ id: "removed", removedAt: PAST }),
    topicRow({ id: "merged", mergedIntoId: "live" }),
  ],
  topicPrimers: [
    topicPrimerRow({ id: "tp-live", topicId: "live" }),
    topicPrimerRow({ id: "tp-old", topicId: "live", isCurrent: 0 }),
    topicPrimerRow({ id: "tp-snoozed", topicId: "live", snoozedUntil: FUTURE }),
    topicPrimerRow({ id: "tp-removed", topicId: "removed" }),
    topicPrimerRow({ id: "tp-merged", topicId: "merged" }),
  ],
};

const keys = (filter: LibraryFilter): string[] => filterEntries(data, filter).map(entryKey).sort();
const ids = (entries: LibraryEntry[]): string[] =>
  entries.map((entry) => (entry.kind === "topicPrimer" ? entry.primer.id : entry.source.id));

describe("filterEntries", () => {
  it("All: every source plus live current topic primers", () => {
    expect(keys("all")).toEqual(
      [
        ...data.sources.map((source) => `source-${source.id}`),
        "topic-primer-tp-live",
        "topic-primer-tp-snoozed",
      ].sort(),
    );
  });

  it("Queued: queued sources and queued primers", () => {
    expect(keys("queued")).toEqual(
      [
        ...["queued", "queued-snoozed", "queued-woke", "queued-with-primer"].map((id) => `source-${id}`),
        ...["done-with-primer", "primer-writing", "primer-snoozed"].map((id) => `queued-primer-${id}`),
      ].sort(),
    );
  });

  it("Done: consumed sources", () => {
    expect(keys("done")).toEqual(
      ["source-done", "source-done-with-primer", "source-primer-snoozed", "source-primer-writing"],
    );
  });

  it("Inbox: inbox and briefed, never a note or a chat item", () => {
    expect(keys("inbox")).toEqual(["source-briefed", "source-inbox"]);
  });

  it("Primers: every source with a primer, queued or not, plus live topic primers; never a chat item's cheat sheet", () => {
    expect(keys("primers")).toEqual([
      "source-done-with-primer",
      "source-queued-with-primer",
      "topic-primer-tp-live",
      "topic-primer-tp-snoozed",
    ]);
  });
});

describe("filterCounts", () => {
  it("leaves snoozed entries out", () => {
    // Queued: 3 awake sources + 2 awake primers (the snoozed source and the snoozed primer are left out).
    expect(filterCounts(data, NOW)).toEqual({ all: 12, queued: 5, done: 4, inbox: 2, primers: 3 });
  });
});

describe("byWeek", () => {
  const sevenDaysAgo = new Date(NOW.getTime() - 7 * 86_400_000).toISOString();
  const justOver = new Date(NOW.getTime() - 7 * 86_400_000 - 1).toISOString();
  const entries: LibraryEntry[] = [
    { kind: "source", source: sourceRow({ id: "old", createdAt: justOver }) },
    { kind: "source", source: sourceRow({ id: "edge", createdAt: sevenDaysAgo }) },
    { kind: "source", source: sourceRow({ id: "new", createdAt: "2026-11-04T10:00:00Z" }) },
    { kind: "source", source: sourceRow({ id: "sleeping", createdAt: "2026-11-04T11:00:00Z", snoozedUntil: FUTURE }) },
    { kind: "topicPrimer", primer: topicPrimerRow({ id: "tp", createdAt: "2026-11-03T00:00:00Z" }), topic: topicRow({}) },
    // A queued primer sleeps by its own snooze time, not its source's.
    {
      kind: "queuedPrimer",
      source: sourceRow({ id: "primer-sleeping", createdAt: "2026-11-04T12:00:00Z", primerSnoozedUntil: FUTURE }),
    },
  ];

  it("splits at exactly 7 days, newest first, with snoozed apart", () => {
    const sections = byWeek(entries, NOW);
    expect(ids(sections.thisWeek)).toEqual(["new", "tp", "edge"]);
    expect(ids(sections.earlier)).toEqual(["old"]);
    expect(ids(sections.snoozed)).toEqual(["primer-sleeping", "sleeping"]);
  });
});
