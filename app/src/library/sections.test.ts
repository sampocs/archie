import type { LibraryData } from "./join";
import { byWeek, entryKey, filterCounts, filterEntries, type LibraryEntry, type LibraryFilter } from "./sections";
import { sourceRow, topicPrimerRow, topicRow } from "./testRows";

const NOW = new Date("2026-11-04T15:00:00Z");
const FUTURE = "2026-11-05T14:00:00Z";
const PAST = "2026-11-04T14:00:00Z";

const data: LibraryData = {
  sources: [
    sourceRow({ id: "queued", state: "queued" }),
    sourceRow({ id: "queued-snoozed", state: "queued", snoozedUntil: FUTURE }),
    sourceRow({ id: "queued-woke", state: "queued", snoozedUntil: PAST }),
    sourceRow({ id: "done", state: "consumed" }),
    sourceRow({ id: "inbox", state: "inbox", kind: "newsletter" }),
    sourceRow({ id: "briefed", state: "briefed", kind: "newsletter" }),
    sourceRow({ id: "prepped", state: "queued", prepMe: 1, primerCreatedAt: PAST }),
    sourceRow({ id: "prepped-no-primer", state: "queued", prepMe: 1 }),
    sourceRow({ id: "primer-not-pushed", state: "queued", primerCreatedAt: PAST }),
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
  entries.map((entry) => (entry.kind === "source" ? entry.source.id : entry.primer.id));

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

  it("Queued: queued sources", () => {
    expect(keys("queued")).toEqual(
      ["queued", "queued-snoozed", "queued-woke", "prepped", "prepped-no-primer", "primer-not-pushed"]
        .map((id) => `source-${id}`)
        .sort(),
    );
  });

  it("Done: consumed sources", () => {
    expect(keys("done")).toEqual(["source-done"]);
  });

  it("Inbox: inbox and briefed", () => {
    expect(keys("inbox")).toEqual(["source-briefed", "source-inbox"]);
  });

  it("Primers: prepped sources with a primer, plus live topic primers", () => {
    expect(keys("primers")).toEqual(["source-prepped", "topic-primer-tp-live", "topic-primer-tp-snoozed"]);
  });
});

describe("filterCounts", () => {
  it("leaves snoozed entries out", () => {
    expect(filterCounts(data, NOW)).toEqual({ all: 9, queued: 5, done: 1, inbox: 2, primers: 2 });
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
  ];

  it("splits at exactly 7 days, newest first, with snoozed apart", () => {
    const sections = byWeek(entries, NOW);
    expect(ids(sections.thisWeek)).toEqual(["new", "tp", "edge"]);
    expect(ids(sections.earlier)).toEqual(["old"]);
    expect(ids(sections.snoozed)).toEqual(["sleeping"]);
  });
});
