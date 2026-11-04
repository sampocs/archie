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
  ...overrides,
});

describe("joinLibrary", () => {
  it("attaches a source's topic, parsed summary and primer time", () => {
    const data = joinLibrary({
      sources: [source({ topicId: "t1" })],
      artifacts: [
        artifact({}),
        artifact({ id: "a2", kind: "primer", content: "{}", createdAt: "2026-11-03T00:00:00Z" }),
      ],
      topics: [topic],
      topicPrimers: [],
    });

    expect(data.sources[0]).toMatchObject({ topic, summary, primerCreatedAt: "2026-11-03T00:00:00Z" });
    expect(data.topics).toEqual([topic]);
  });

  it("gives nulls to a source without a topic or artifacts", () => {
    const data = joinLibrary({
      sources: [source({ id: "s2" })],
      artifacts: [artifact({})],
      topics: [topic],
      topicPrimers: [],
    });

    expect(data.sources[0]).toMatchObject({ topic: null, summary: null, primerCreatedAt: null });
  });
});
