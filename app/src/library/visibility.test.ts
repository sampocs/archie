import type { LibraryData, LibrarySource, TopicPrimerRow, TopicRow } from "./join";
import { isSnoozed, primersReady, statusTag, upNext, waitingNewsletters } from "./visibility";

const NOW = new Date("2026-11-04T15:00:00Z");
const PAST = "2026-11-04T14:00:00Z";
const FUTURE = "2026-11-05T14:00:00Z";

const source = (overrides: Partial<LibrarySource>): LibrarySource => ({
  id: "s1",
  url: "https://example.com/a",
  title: "A",
  kind: "article",
  state: "inbox",
  intent: "queue",
  createdAt: "2026-11-01T00:00:00Z",
  updatedAt: "2026-11-01T00:00:00Z",
  deletedAt: null,
  syncError: null,
  processing: "ready",
  processingError: null,
  reaction: null,
  note: null,
  prepMe: 0,
  mergedIntoId: null,
  sender: null,
  domain: null,
  topicId: null,
  imageUrl: null,
  queuePosition: null,
  readAt: null,
  snoozedUntil: null,
  primerOpenedAt: null,
  newsletterKind: null,
  topic: null,
  summary: null,
  primerCreatedAt: null,
  ...overrides,
});

const topic = (overrides: Partial<TopicRow>): TopicRow => ({
  id: "t1",
  domain: "AI",
  name: "Agents",
  origin: "user",
  removedAt: null,
  mergedIntoId: null,
  createdAt: "2026-11-01T00:00:00Z",
  updatedAt: "2026-11-01T00:00:00Z",
  primerRequestedAt: null,
  ...overrides,
});

const topicPrimer = (overrides: Partial<TopicPrimerRow>): TopicPrimerRow => ({
  id: "p1",
  topicId: "t1",
  version: 1,
  isCurrent: 1,
  content: JSON.stringify({ markdown: "# Agents" }),
  openedAt: null,
  snoozedUntil: null,
  createdAt: "2026-11-03T00:00:00Z",
  ...overrides,
});

describe("statusTag", () => {
  it.each([
    [{ state: "queued", processing: "pending", readAt: null }, "Processing"],
    [{ state: "consumed", processing: "processing", readAt: null }, "Processing"],
    [{ state: "queued", processing: "failed", readAt: null }, "Failed"],
    [{ state: "queued", processing: "ready", readAt: null }, "Queued"],
    [{ state: "consumed", processing: "ready", readAt: null }, "Done"],
    [{ state: "briefed", processing: "ready", readAt: null }, "Briefed"],
    [{ state: "inbox", processing: "ready", readAt: null }, "Unread"],
    [{ state: "inbox", processing: "ready", readAt: PAST }, "Read"],
  ] as const)("%p → %s", (row, expected) => {
    expect(statusTag(row)).toBe(expected);
  });
});

describe("isSnoozed", () => {
  it("is snoozed only until a future time", () => {
    expect(isSnoozed({ snoozedUntil: FUTURE }, NOW)).toBe(true);
    expect(isSnoozed({ snoozedUntil: PAST }, NOW)).toBe(false);
    expect(isSnoozed({ snoozedUntil: null }, NOW)).toBe(false);
  });
});

describe("upNext", () => {
  it("lists visible queued sources by position, then unpositioned ones newest first", () => {
    const sources = [
      source({ id: "unpositioned-old", state: "queued", createdAt: "2026-11-01T00:00:00Z" }),
      source({ id: "second", state: "queued", queuePosition: 2 }),
      source({ id: "snoozed", state: "queued", queuePosition: -5, snoozedUntil: FUTURE }),
      source({ id: "unpositioned-new", state: "queued", createdAt: "2026-11-02T00:00:00Z" }),
      source({ id: "first", state: "queued", queuePosition: -1 }),
      source({ id: "inbox", state: "inbox", queuePosition: -9 }),
    ];

    expect(upNext(sources, NOW).map((item) => item.id)).toEqual([
      "first",
      "second",
      "unpositioned-new",
      "unpositioned-old",
    ]);
  });
});

describe("primersReady", () => {
  const data = (sources: LibrarySource[], topics: TopicRow[], topicPrimers: TopicPrimerRow[]): LibraryData => ({
    sources,
    topics,
    topicPrimers,
  });

  it("lists prepped source primers and live topic primers nobody opened, newest first", () => {
    const items = primersReady(
      data(
        [source({ id: "prepped", prepMe: 1, primerCreatedAt: "2026-11-02T00:00:00Z" })],
        [topic({})],
        [topicPrimer({})],
      ),
      NOW,
    );

    expect(items.map((item) => item.key)).toEqual(["topic-p1", "source-prepped"]);
  });

  it("leaves out opened, snoozed, un-prepped, primerless, removed-topic and merged-topic primers", () => {
    const items = primersReady(
      data(
        [
          source({ id: "opened", prepMe: 1, primerCreatedAt: PAST, primerOpenedAt: PAST }),
          source({ id: "snoozed", prepMe: 1, primerCreatedAt: PAST, snoozedUntil: FUTURE }),
          source({ id: "unprepped", prepMe: 0, primerCreatedAt: PAST }),
          source({ id: "no-primer", prepMe: 1 }),
        ],
        [topic({ id: "removed", removedAt: PAST }), topic({ id: "merged", mergedIntoId: "t9" }), topic({ id: "live" })],
        [
          topicPrimer({ id: "p-removed", topicId: "removed" }),
          topicPrimer({ id: "p-merged", topicId: "merged" }),
          topicPrimer({ id: "p-opened", topicId: "live", openedAt: PAST }),
          topicPrimer({ id: "p-snoozed", topicId: "live", snoozedUntil: FUTURE }),
        ],
      ),
      NOW,
    );

    expect(items).toEqual([]);
  });
});

describe("waitingNewsletters", () => {
  it("counts inbox newsletters that aren't snoozed, names the two newest senders, and gives the oldest time", () => {
    const newsletter = (overrides: Partial<LibrarySource>) =>
      source({ kind: "newsletter", state: "inbox", ...overrides });
    const result = waitingNewsletters(
      [
        newsletter({ id: "n1", sender: "Stratechery", createdAt: "2026-11-01T00:00:00Z" }),
        newsletter({ id: "n2", sender: "Matt Levine", createdAt: "2026-11-03T00:00:00Z" }),
        newsletter({ id: "n3", sender: "Stratechery", createdAt: "2026-11-04T00:00:00Z" }),
        newsletter({ id: "n4", sender: "The Diff", createdAt: "2026-11-02T00:00:00Z" }),
        newsletter({ id: "briefed", state: "briefed", sender: "Briefed" }),
        newsletter({ id: "snoozed", sender: "Snoozed", snoozedUntil: FUTURE }),
        source({ id: "article", state: "inbox" }),
      ],
      NOW,
    );

    expect(result).toEqual({ count: 4, senders: ["Stratechery", "Matt Levine"], since: "2026-11-01T00:00:00Z" });
  });
});
