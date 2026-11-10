import type * as schema from "@/db/schema";

import { joinLibrary, type SourceRow, type TopicRow } from "./join";

type ArtifactRow = typeof schema.artifacts.$inferSelect;

const source = (overrides: Partial<SourceRow>): SourceRow => ({
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
  mergedIntoId: null,
  sender: null,
  domain: null,
  topicId: null,
  imageUrl: null,
  queuePosition: null,
  readAt: null,
  snoozedUntil: null,
  primerOpenedAt: null,
  primerQueuePosition: null,
  primerSnoozedUntil: null,
  newsletterKind: null,
  cardsOff: 0,
  favoritedAt: null,
  publishedAt: null,
  confirmUrl: null,
  noteMarkdown: null,
  noteEditedAt: null,
  refreshedAt: null,
  refreshedFromQueue: 0,
  refreshSkippedAt: null,
  senderAddress: null,
  senderPending: false,
  chatConversationId: null,
  ...overrides,
});

const topic: TopicRow = {
  id: "t1",
  domain: "Crypto",
  name: "Bitcoin",
  origin: "starter",
  removedAt: null,
  mergedIntoId: null,
  createdAt: "2026-11-01T00:00:00Z",
  updatedAt: "2026-11-01T00:00:00Z",
  primerRequestedAt: null,
};

const summary = { gist: "One line", key_ideas: [], numbers: [] };

const artifact = (overrides: Partial<ArtifactRow>): ArtifactRow => ({
  id: "a1",
  sourceId: "s1",
  kind: "summary",
  version: 1,
  content: JSON.stringify({ summary }),
  isCurrent: 1,
  createdAt: "2026-11-02T00:00:00Z",
  origin: "archie",
  instruction: null,
  ...overrides,
});

describe("joinLibrary", () => {
  it("attaches a source's topic, parsed summary, primer time and primer length", () => {
    const data = joinLibrary({
      sources: [source({ topicId: "t1" })],
      artifacts: [
        artifact({}),
        artifact({
          id: "a2",
          kind: "primer",
          content: JSON.stringify({ markdown: "# Grid\n\nPower sets  the pace." }),
          createdAt: "2026-11-03T00:00:00Z",
        }),
      ],
      topics: [topic],
      topicPrimers: [],
      cardCounts: new Map(),
    });

    expect(data.sources[0]).toMatchObject({
      topic,
      summary,
      primerCreatedAt: "2026-11-03T00:00:00Z",
      primerWords: 6,
    });
    expect(data.topics).toEqual([topic]);
  });

  it("gives nulls to a source without a topic or artifacts", () => {
    const data = joinLibrary({
      sources: [source({ id: "s2" })],
      artifacts: [artifact({})],
      topics: [topic],
      topicPrimers: [],
      cardCounts: new Map(),
    });

    expect(data.sources[0]).toMatchObject({ topic: null, summary: null, primerCreatedAt: null, primerWords: null });
  });

  it("splits confirmation emails out of sources into confirmations, newest first", () => {
    const data = joinLibrary({
      sources: [
        source({ id: "old", confirmUrl: "https://example.com/a", createdAt: "2026-11-02T00:00:00Z" }),
        source({ id: "plain" }),
        source({ id: "new", confirmUrl: "https://example.com/b", createdAt: "2026-11-05T00:00:00Z" }),
      ],
      artifacts: [],
      topics: [],
      topicPrimers: [],
      cardCounts: new Map(),
    });

    expect(data.sources.map((row) => row.id)).toEqual(["plain"]);
    expect(data.confirmations.map((row) => row.id)).toEqual(["new", "old"]);
    expect(data.confirmations[0]).toMatchObject({ topic: null, summary: null });
    expect(data.pendingSenders).toEqual([]);
  });

  it("splits sources awaiting a sender decision out into pendingSenders, newest first, and a confirmation is never pending", () => {
    const data = joinLibrary({
      sources: [
        source({ id: "old", senderPending: true, createdAt: "2026-11-02T00:00:00Z" }),
        source({ id: "plain" }),
        source({ id: "new", senderPending: true, createdAt: "2026-11-05T00:00:00Z" }),
        source({ id: "confirm", senderPending: true, confirmUrl: "https://example.com/c" }),
      ],
      artifacts: [],
      topics: [],
      topicPrimers: [],
      cardCounts: new Map(),
    });

    expect(data.sources.map((row) => row.id)).toEqual(["plain"]);
    expect(data.pendingSenders.map((row) => row.id)).toEqual(["new", "old"]);
    expect(data.confirmations.map((row) => row.id)).toEqual(["confirm"]);
  });

  it("gives each source its live card count, 0 when it has none", () => {
    const data = joinLibrary({
      sources: [source({ id: "with" }), source({ id: "without" })],
      artifacts: [],
      topics: [],
      topicPrimers: [],
      cardCounts: new Map([["with", 5]]),
    });

    expect(data.sources.map((row) => row.cardCount)).toEqual([5, 0]);
  });
});
