import Database from "better-sqlite3";
import { drizzle } from "drizzle-orm/better-sqlite3";
import { eq } from "drizzle-orm";

import {
  addSource,
  addTopic,
  chooseTopics,
  dropCard,
  finishBrief,
  finishPrimer,
  finishSource,
  goDeeper,
  mergeTopic,
  queuePrimer,
  readLater,
  removeTopic,
  requestNewsQuiz,
  requestPrimer,
  restoreTopic,
  retrySource,
  returnToInbox,
  reviewCard,
  setCardsOff,
  setQueuePosition,
  setSourceTopic,
  snooze,
} from "./actions";
import type { AppDb } from "./client";
import * as schema from "./schema";
import { makeTestDb } from "./testDb";

// expo-crypto is a native module; node's crypto gives the same UUIDs.
jest.mock("expo-crypto", () => ({ randomUUID: () => require("crypto").randomUUID() }));

function createTables(outboxCheck: string): string {
  return `
    CREATE TABLE sources (
      id text PRIMARY KEY NOT NULL, url text NOT NULL, title text, kind text NOT NULL, state text NOT NULL,
      intent text NOT NULL, created_at text NOT NULL, updated_at text NOT NULL, deleted_at text, sync_error text,
      processing text DEFAULT 'pending' NOT NULL, processing_error text, reaction text, note text,
      merged_into_id text, sender text, domain text, topic_id text, image_url text, queue_position real,
      read_at text, snoozed_until text, primer_opened_at text, newsletter_kind text, primer_queue_position real,
      primer_snoozed_until text, cards_off integer DEFAULT 0 NOT NULL
    );
    CREATE TABLE outbox (
      id text PRIMARY KEY NOT NULL, type text NOT NULL, payload text NOT NULL, created_at text NOT NULL,
      status text NOT NULL, error text${outboxCheck}
    );
  `;
}

// `rejectOutboxType` adds a CHECK that makes the outbox insert fail, to prove the source insert rolls back with it.
function makeDb(rejectOutboxType?: string): AppDb {
  const sqlite = new Database(":memory:");
  sqlite.exec(createTables(rejectOutboxType ? `, CHECK (type != '${rejectOutboxType}')` : ""));
  return drizzle(sqlite, { schema }) as unknown as AppDb;
}

describe("addSource", () => {
  it("writes one source and one pending outbox row sharing the same id", async () => {
    const db = makeDb();

    const id = await addSource(db, { url: "https://example.com/a", intent: "queue" });

    const sourceRows = db.select().from(schema.sources).all();
    const outboxRows = db.select().from(schema.outbox).all();
    expect(sourceRows).toHaveLength(1);
    expect(sourceRows[0]).toMatchObject({ id, kind: "link", state: "queued", intent: "queue" });
    expect(outboxRows).toHaveLength(1);
    expect(outboxRows[0]).toMatchObject({ type: "add_source", status: "pending" });
    expect(JSON.parse(outboxRows[0].payload)).toEqual({ id, url: "https://example.com/a", intent: "queue" });
    expect(sourceRows[0]).toMatchObject({ processing: "pending", reaction: null, note: null, primerQueuePosition: null });
  });

  it("sends reaction and note for a finished source, and queue_primer for a queued one, in snake_case", async () => {
    const db = makeDb();

    const finishedId = await addSource(db, {
      url: "https://example.com/f",
      intent: "finished",
      reaction: "lost",
      note: "the second half",
    });
    const queuedId = await addSource(db, { url: "https://example.com/q", intent: "queue", queuePrimer: true });

    const payloads = db.select().from(schema.outbox).all().map((row) => JSON.parse(row.payload));
    expect(payloads).toContainEqual({
      id: finishedId,
      url: "https://example.com/f",
      intent: "finished",
      reaction: "lost",
      note: "the second half",
    });
    expect(payloads).toContainEqual({ id: queuedId, url: "https://example.com/q", intent: "queue", queue_primer: true });
    // The primer goes just above its item, so it's read first.
    expect(db.select().from(schema.sources).where(eq(schema.sources.id, queuedId)).get()).toMatchObject({
      queuePosition: 0,
      primerQueuePosition: -1,
    });
  });

  it("never queues a primer for a finished capture", async () => {
    const db = makeDb();

    const id = await addSource(db, { url: "https://example.com/f", intent: "finished", queuePrimer: true });

    expect(db.select().from(schema.sources).get()?.primerQueuePosition).toBeNull();
    expect(JSON.parse(db.select().from(schema.outbox).get()!.payload)).toEqual({
      id,
      url: "https://example.com/f",
      intent: "finished",
    });
  });

  it("leaves no source row behind when the outbox insert throws", async () => {
    const db = makeDb("add_source");

    await expect(addSource(db, { url: "https://example.com/b", intent: "finished" })).rejects.toThrow();

    expect(db.select().from(schema.sources).all()).toHaveLength(0);
    expect(db.select().from(schema.outbox).all()).toHaveLength(0);
  });
});

describe("retrySource", () => {
  const seedFailed = (db: AppDb) =>
    db
      .insert(schema.sources)
      .values({
        id: "s1", url: "https://example.com/a", kind: "article", state: "queued", intent: "queue",
        createdAt: "x", updatedAt: "x", processing: "failed", processingError: "text_missing",
      })
      .run();

  it("marks the source processing, clears the error, and queues a retry_source action", async () => {
    const db = makeDb();
    seedFailed(db);

    await retrySource(db, "s1");

    const source = db.select().from(schema.sources).get();
    expect(source).toMatchObject({ processing: "processing", processingError: null });
    const outboxRows = db.select().from(schema.outbox).all();
    expect(outboxRows).toHaveLength(1);
    expect(outboxRows[0]).toMatchObject({ type: "retry_source", status: "pending" });
    expect(JSON.parse(outboxRows[0].payload)).toEqual({ id: "s1" });
  });

  it("rolls the status change back when the outbox insert throws", async () => {
    const db = makeDb("retry_source");
    seedFailed(db);

    await expect(retrySource(db, "s1")).rejects.toThrow();

    expect(db.select().from(schema.sources).get()).toMatchObject({ processing: "failed", processingError: "text_missing" });
  });
});

// Rows for the M4 actions; every case runs on the app's real migrated schema.
const seedSource = (db: AppDb, overrides: Partial<typeof schema.sources.$inferInsert>) =>
  db
    .insert(schema.sources)
    .values({
      id: "s1", url: "https://example.com/a", kind: "article", state: "inbox", intent: "queue",
      createdAt: "2026-11-01T00:00:00Z", updatedAt: "2026-11-01T00:00:00Z", processing: "ready",
      ...overrides,
    })
    .run();

const seedTopic = (db: AppDb, overrides: Partial<typeof schema.topics.$inferInsert>) =>
  db
    .insert(schema.topics)
    .values({
      id: "t1", domain: "Crypto", name: "Bitcoin", origin: "starter",
      createdAt: "2026-11-01T00:00:00Z", updatedAt: "2026-11-01T00:00:00Z",
      ...overrides,
    })
    .run();

const sourceById = (db: AppDb, id: string) => db.select().from(schema.sources).where(eq(schema.sources.id, id)).get();

const outboxEntries = (db: AppDb) =>
  db.select().from(schema.outbox).all().map((row) => ({ type: row.type, payload: JSON.parse(row.payload) }));

const seedPrimer = (db: AppDb, sourceId: string) =>
  db
    .insert(schema.artifacts)
    .values({
      id: `primer-${sourceId}`, sourceId, kind: "primer", version: 1, content: JSON.stringify({ markdown: "x" }),
      isCurrent: 1, createdAt: "2026-11-02T00:00:00Z",
    })
    .run();

describe("finishSource", () => {
  it("marks a lost source consumed without queueing its primer, and leaves an empty note out of the payload", () => {
    const db = makeTestDb();
    seedSource(db, { state: "queued", snoozedUntil: "2026-11-09T14:00:00.000Z" });

    finishSource(db, { sourceId: "s1", reaction: "lost", note: null, queuePrimer: false });

    expect(sourceById(db, "s1")).toMatchObject({
      state: "consumed",
      reaction: "lost",
      snoozedUntil: null,
      primerQueuePosition: null,
      processing: "ready",
    });
    expect(outboxEntries(db)).toEqual([{ type: "finish_source", payload: { id: "s1", reaction: "lost" } }]);
  });

  it("queues the primer at the top of the shared queue when asked", () => {
    const db = makeTestDb();
    seedSource(db, { id: "queued", state: "queued", queuePosition: -2 });
    seedSource(db, { id: "primer", state: "consumed", primerQueuePosition: -5 });
    seedSource(db, { id: "s1", state: "queued", queuePosition: 3 });
    seedPrimer(db, "s1");

    finishSource(db, { sourceId: "s1", reaction: "lost", note: null, queuePrimer: true });

    expect(sourceById(db, "s1")).toMatchObject({ state: "consumed", primerQueuePosition: -6, processing: "ready" });
    expect(outboxEntries(db)).toEqual([
      { type: "finish_source", payload: { id: "s1", reaction: "lost", queue_primer: true } },
    ]);
  });

  it("re-runs a finished newsletter's analysis, so it shows as processing", () => {
    const db = makeTestDb();
    seedSource(db, { kind: "newsletter", state: "queued", processing: "ready", processingError: "old" });

    finishSource(db, { sourceId: "s1", reaction: null, note: null });

    expect(sourceById(db, "s1")).toMatchObject({ state: "consumed", processing: "processing", processingError: null });
  });

  it("leaves a newsletter that is still processing alone, since its queued analysis makes the cards", () => {
    const db = makeTestDb();
    seedSource(db, { kind: "newsletter", state: "queued", processing: "processing", processingError: "old" });

    finishSource(db, { sourceId: "s1", reaction: null, note: null });

    expect(sourceById(db, "s1")).toMatchObject({ state: "consumed", processing: "processing", processingError: "old" });
  });
});

describe("queuePrimer", () => {
  it("queues a primer above both queued sources and queued primers, clearing its snooze", () => {
    const db = makeTestDb();
    seedSource(db, { id: "queued", state: "queued", queuePosition: -4 });
    seedSource(db, { id: "other-primer", state: "consumed", primerQueuePosition: -2 });
    seedSource(db, { id: "s1", state: "queued", queuePosition: 1, primerSnoozedUntil: "2099-01-01T00:00:00Z" });

    queuePrimer(db, "s1", true);

    expect(sourceById(db, "s1")).toMatchObject({ primerQueuePosition: -5, primerSnoozedUntil: null, queuePosition: 1 });
    expect(outboxEntries(db)).toEqual([{ type: "queue_primer", payload: { id: "s1", queued: true } }]);
  });

  it("takes a queued primer out of the queue", () => {
    const db = makeTestDb();
    seedSource(db, { primerQueuePosition: 2 });

    queuePrimer(db, "s1", false);

    expect(sourceById(db, "s1")?.primerQueuePosition).toBeNull();
    expect(outboxEntries(db)).toEqual([{ type: "queue_primer", payload: { id: "s1", queued: false } }]);
  });

  it("starts writing a newsletter's primer only when it has none and nothing is running", () => {
    const db = makeTestDb();
    seedSource(db, { id: "bare", kind: "newsletter" });
    seedSource(db, { id: "has-primer", kind: "newsletter" });
    seedPrimer(db, "has-primer");
    seedSource(db, { id: "article", kind: "article" });

    queuePrimer(db, "bare", true);
    queuePrimer(db, "has-primer", true);
    queuePrimer(db, "article", true);

    expect(sourceById(db, "bare")?.processing).toBe("processing");
    expect(sourceById(db, "has-primer")?.processing).toBe("ready");
    expect(sourceById(db, "article")?.processing).toBe("ready");
  });
});

describe("finishPrimer", () => {
  it("takes the primer off the queue and marks it opened, sending both actions", () => {
    const db = makeTestDb();
    seedSource(db, { primerQueuePosition: 0 });

    finishPrimer(db, "s1");

    const source = sourceById(db, "s1");
    expect(source?.primerQueuePosition).toBeNull();
    expect(source?.primerOpenedAt).not.toBeNull();
    expect(outboxEntries(db)).toEqual(
      expect.arrayContaining([
        { type: "queue_primer", payload: { id: "s1", queued: false } },
        { type: "set_primer_opened", payload: { target: "source", id: "s1", opened: true } },
      ]),
    );
    expect(outboxEntries(db)).toHaveLength(2);
  });
});

describe("requestPrimer", () => {
  it("shows the newsletter as processing and sends request_primer", () => {
    const db = makeTestDb();
    seedSource(db, { kind: "newsletter", state: "consumed", processing: "failed", processingError: "boom" });

    requestPrimer(db, "s1");

    expect(sourceById(db, "s1")).toMatchObject({ processing: "processing", processingError: null });
    expect(outboxEntries(db)).toEqual([{ type: "request_primer", payload: { id: "s1" } }]);
  });
});

describe("returnToInbox", () => {
  it("puts a queued newsletter back in the inbox, out of the queue", () => {
    const db = makeTestDb();
    seedSource(db, { kind: "newsletter", state: "queued", queuePosition: -1 });

    returnToInbox(db, "s1");

    expect(sourceById(db, "s1")).toMatchObject({ state: "inbox", queuePosition: null });
    expect(outboxEntries(db)).toEqual([{ type: "return_to_inbox", payload: { id: "s1" } }]);
  });
});

describe("setQueuePosition", () => {
  it("moves the source or its primer depending on the target, and sends the target", () => {
    const db = makeTestDb();
    seedSource(db, { state: "queued", queuePosition: 1, primerQueuePosition: 2 });

    setQueuePosition(db, "s1", 5, "source_primer");
    expect(sourceById(db, "s1")).toMatchObject({ queuePosition: 1, primerQueuePosition: 5 });

    setQueuePosition(db, "s1", -3);
    expect(sourceById(db, "s1")).toMatchObject({ queuePosition: -3, primerQueuePosition: 5 });

    expect(outboxEntries(db)).toEqual([
      { type: "set_queue_position", payload: { id: "s1", position: 5, target: "source_primer" } },
      { type: "set_queue_position", payload: { id: "s1", position: -3, target: "source" } },
    ]);
  });
});

describe("snooze", () => {
  it("moves a snoozed queued source above the top of the queue and sends `until` as an ISO string", () => {
    const db = makeTestDb();
    seedSource(db, { id: "top", state: "queued", queuePosition: -3 });
    seedSource(db, { id: "s1", state: "queued", queuePosition: 4 });
    const until = new Date("2026-11-05T14:00:00.000Z");

    snooze(db, "source", "s1", until);

    expect(sourceById(db, "s1")).toMatchObject({ snoozedUntil: until.toISOString(), queuePosition: -4 });
    expect(outboxEntries(db)).toEqual([
      { type: "snooze", payload: { target: "source", id: "s1", until: "2026-11-05T14:00:00.000Z" } },
    ]);
  });

  it("snoozes a queued primer apart from its source and brings it back above the top", () => {
    const db = makeTestDb();
    seedSource(db, { id: "top", state: "queued", queuePosition: -3 });
    seedSource(db, { id: "s1", state: "queued", queuePosition: 4, primerQueuePosition: 2 });
    const until = new Date("2026-11-05T14:00:00.000Z");

    snooze(db, "source_primer", "s1", until);

    expect(sourceById(db, "s1")).toMatchObject({
      primerSnoozedUntil: until.toISOString(),
      primerQueuePosition: -4,
      snoozedUntil: null,
      queuePosition: 4,
    });
    expect(outboxEntries(db)).toEqual([
      { type: "snooze", payload: { target: "source_primer", id: "s1", until: "2026-11-05T14:00:00.000Z" } },
    ]);
  });

  it("sends `until: null` to unsnooze", () => {
    const db = makeTestDb();
    seedSource(db, { state: "queued", queuePosition: 1, snoozedUntil: "2026-11-05T14:00:00.000Z" });

    snooze(db, "source", "s1", null);

    expect(sourceById(db, "s1")).toMatchObject({ snoozedUntil: null, queuePosition: 1 });
    expect(outboxEntries(db)).toEqual([{ type: "snooze", payload: { target: "source", id: "s1", until: null } }]);
  });
});

describe("readLater", () => {
  it("queues an inbox source at the top of the queue", () => {
    const db = makeTestDb();
    seedSource(db, { id: "queued", state: "queued", queuePosition: 2 });
    seedSource(db, { id: "s1", state: "inbox" });

    readLater(db, "s1");

    expect(sourceById(db, "s1")).toMatchObject({ state: "queued", queuePosition: 1 });
    expect(outboxEntries(db)).toEqual([{ type: "read_later", payload: { id: "s1" } }]);
  });
});

describe("goDeeper", () => {
  it("keeps an existing read time and sets one when the source was unread", () => {
    const db = makeTestDb();
    seedSource(db, { id: "read", readAt: "2026-11-01T00:00:00Z" });
    seedSource(db, { id: "unread" });

    goDeeper(db, "read");
    goDeeper(db, "unread");

    expect(sourceById(db, "read")).toMatchObject({
      state: "consumed",
      processing: "processing",
      readAt: "2026-11-01T00:00:00Z",
    });
    expect(sourceById(db, "unread")?.readAt).not.toBeNull();
  });

  it("turns cards back on, as the server's go_deeper does", () => {
    const db = makeTestDb();
    seedSource(db, { id: "off", cardsOff: 1 });

    goDeeper(db, "off");

    expect(sourceById(db, "off")?.cardsOff).toBe(0);
  });

  it("clears a snooze", () => {
    const db = makeTestDb();
    seedSource(db, { id: "snoozed", snoozedUntil: "2099-01-01T00:00:00Z" });

    goDeeper(db, "snoozed");

    expect(sourceById(db, "snoozed")?.snoozedUntil).toBeNull();
  });
});

describe("addSource queue position", () => {
  it("puts each newly queued source above the last one, starting at 0", async () => {
    const db = makeTestDb();

    const first = await addSource(db, { url: "https://example.com/1", intent: "queue" });
    const second = await addSource(db, { url: "https://example.com/2", intent: "queue" });
    const finished = await addSource(db, { url: "https://example.com/3", intent: "finished" });

    expect(sourceById(db, first)?.queuePosition).toBe(0);
    expect(sourceById(db, second)?.queuePosition).toBe(-1);
    expect(sourceById(db, finished)?.queuePosition).toBeNull();
  });
});

describe("topic actions", () => {
  it("mergeTopic moves the topic's sources, with the target's domain, and marks it merged", () => {
    const db = makeTestDb();
    seedTopic(db, { id: "from", domain: "Crypto", name: "BTC" });
    seedTopic(db, { id: "into", domain: "Finance", name: "Bitcoin investing" });
    seedSource(db, { id: "s1", topicId: "from", domain: "Crypto" });

    mergeTopic(db, "from", "into");

    expect(sourceById(db, "s1")).toMatchObject({ topicId: "into", domain: "Finance" });
    expect(db.select().from(schema.topics).where(eq(schema.topics.id, "from")).get()?.mergedIntoId).toBe("into");
    expect(outboxEntries(db)).toEqual([{ type: "merge_topic", payload: { id: "from", into_id: "into" } }]);
  });

  it("setSourceTopic to an unknown topic keeps the source's domain", () => {
    const db = makeTestDb();
    seedSource(db, { domain: "Crypto" });

    setSourceTopic(db, "s1", "missing");

    expect(sourceById(db, "s1")).toMatchObject({ topicId: "missing", domain: "Crypto" });
  });

  it("mergeTopic bumps updatedAt on the topic and its sources", () => {
    const db = makeTestDb();
    seedTopic(db, { id: "from", updatedAt: "2026-11-01T00:00:00Z" });
    seedTopic(db, { id: "into", name: "Other" });
    seedSource(db, { topicId: "from" });

    mergeTopic(db, "from", "into");
    expect(sourceById(db, "s1")?.updatedAt).not.toBe("2026-11-01T00:00:00Z");
    expect(db.select().from(schema.topics).where(eq(schema.topics.id, "from")).get()?.updatedAt).not.toBe(
      "2026-11-01T00:00:00Z",
    );
  });

  it("removeTopic and restoreTopic bump the topic's updatedAt, and removeTopic the sources'", () => {
    const db = makeTestDb();
    const stale = "2026-11-01T00:00:00Z";
    const topicUpdatedAt = () => db.select().from(schema.topics).get()?.updatedAt;
    seedTopic(db, {});
    seedSource(db, { topicId: "t1" });

    removeTopic(db, "t1");
    expect(topicUpdatedAt()).not.toBe(stale);
    expect(sourceById(db, "s1")?.updatedAt).not.toBe(stale);

    db.update(schema.topics).set({ updatedAt: stale }).run();
    restoreTopic(db, "t1");
    expect(topicUpdatedAt()).not.toBe(stale);
  });

  it("removeTopic marks it removed and clears it from its sources", () => {
    const db = makeTestDb();
    seedTopic(db, {});
    seedSource(db, { topicId: "t1", domain: "Crypto" });

    removeTopic(db, "t1");

    expect(sourceById(db, "s1")).toMatchObject({ topicId: null, domain: "Crypto" });
    expect(db.select().from(schema.topics).get()?.removedAt).not.toBeNull();
    expect(outboxEntries(db)).toEqual([{ type: "remove_topic", payload: { id: "t1" } }]);
  });

  it("chooseTopics inserts every topic and sends them as {id, domain, name}", () => {
    const db = makeTestDb();

    chooseTopics(db, [
      { domain: "Crypto", name: "Bitcoin", origin: "starter" },
      { domain: "AI", name: "Evals", origin: "user" },
    ]);

    const rows = db.select().from(schema.topics).all();
    expect(rows.map((row) => [row.name, row.origin, row.primerRequestedAt !== null])).toEqual([
      ["Bitcoin", "starter", false],
      ["Evals", "user", true],
    ]);
    expect(outboxEntries(db)).toEqual([
      {
        type: "choose_topics",
        payload: {
          topics: rows.map((row) => ({ id: row.id, domain: row.domain, name: row.name })),
        },
      },
    ]);
  });

  it("addTopic returns the id it sends, with the name's spacing collapsed", () => {
    const db = makeTestDb();

    const id = addTopic(db, { domain: "AI", name: "  AI   evals " });

    expect(db.select().from(schema.topics).get()).toMatchObject({ id, name: "AI evals", origin: "user" });
    expect(outboxEntries(db)).toEqual([{ type: "add_topic", payload: { id, domain: "AI", name: "AI evals" } }]);
  });
});

describe("finishBrief", () => {
  it("closes the brief and marks only its covered inbox newsletters briefed, sending the newsletters it showed", () => {
    const db = makeTestDb();
    seedSource(db, { id: "covered", kind: "newsletter", state: "inbox" });
    seedSource(db, { id: "queued", kind: "newsletter", state: "queued", queuePosition: 0 });
    seedSource(db, { id: "later", kind: "newsletter", state: "inbox" });
    db.insert(schema.briefs)
      .values({
        id: "b1", status: "open", content: null, sourceIds: JSON.stringify(["covered", "queued"]), since: null,
        version: 3, createdAt: "2026-11-04T00:00:00Z", updatedAt: "2026-11-04T00:00:00Z",
      })
      .run();

    finishBrief(db, "b1");

    const brief = db.select().from(schema.briefs).where(eq(schema.briefs.id, "b1")).get();
    expect(brief?.status).toBe("done");
    expect(brief?.doneAt).not.toBeNull();
    expect(sourceById(db, "covered")?.state).toBe("briefed");
    expect(sourceById(db, "queued")?.state).toBe("queued");
    expect(sourceById(db, "later")?.state).toBe("inbox");
    expect(outboxEntries(db)).toEqual([{ type: "finish_brief", payload: { id: "b1", source_ids: ["covered", "queued"] } }]);
  });
});

const seedCard = (db: AppDb, overrides: Partial<typeof schema.cards.$inferInsert>) =>
  db
    .insert(schema.cards)
    .values({ id: "c1", sourceId: "s1", kind: "concept", question: "Q?", answer: "A.", createdAt: "2026-11-01T00:00:00Z", ...overrides })
    .run();

const cardById = (db: AppDb, id: string) => db.select().from(schema.cards).where(eq(schema.cards.id, id)).get();

describe("review actions", () => {
  const before = {
    fsrsState: "new" as const,
    stability: null,
    difficulty: null,
    dueAt: null,
    lastReviewAt: null,
    reps: 0,
    lapses: 0,
  };
  const after = {
    fsrsState: "review" as const,
    stability: 3.2,
    difficulty: 4.9,
    dueAt: "2026-11-08T12:00:00.000Z",
    lastReviewAt: "2026-11-05T12:00:00.000Z",
    reps: 1,
    lapses: 0,
  };

  it("reviewCard logs the review, schedules the card and sends both states in snake_case", () => {
    const db = makeTestDb();
    seedCard(db, {});

    const reviewId = reviewCard(db, {
      cardId: "c1",
      grade: "got_it",
      gradedBy: "model",
      answer: "my answer",
      missing: "",
      wasDue: true,
      reviewedAt: new Date("2026-11-05T12:00:00Z"),
      stateBefore: before,
      stateAfter: after,
    });

    const review = db.select().from(schema.reviews).all();
    expect(review).toEqual([
      {
        id: reviewId,
        cardId: "c1",
        grade: "got_it",
        gradedBy: "model",
        answer: "my answer",
        missing: "",
        wasDue: 1,
        reviewedAt: "2026-11-05T12:00:00.000Z",
        stateBefore: JSON.stringify(before),
        stateAfter: JSON.stringify(after),
        replacesReviewId: null,
      },
    ]);
    expect(cardById(db, "c1")).toMatchObject(after);
    expect(outboxEntries(db)).toEqual([
      {
        type: "review_card",
        payload: {
          id: "c1",
          review_id: reviewId,
          grade: "got_it",
          graded_by: "model",
          answer: "my answer",
          missing: "",
          was_due: true,
          reviewed_at: "2026-11-05T12:00:00.000Z",
          state_before: {
            fsrs_state: "new", stability: null, difficulty: null, due_at: null, last_review_at: null, reps: 0, lapses: 0,
          },
          state_after: {
            fsrs_state: "review",
            stability: 3.2,
            difficulty: 4.9,
            due_at: "2026-11-08T12:00:00.000Z",
            last_review_at: "2026-11-05T12:00:00.000Z",
            reps: 1,
            lapses: 0,
          },
          replaces_review_id: null,
        },
      },
    ]);
  });

  it("reviewCard stores an early review as not due and sends the review it replaces", () => {
    const db = makeTestDb();
    seedCard(db, {});

    reviewCard(db, {
      cardId: "c1",
      grade: "partly",
      gradedBy: "self",
      answer: null,
      missing: null,
      wasDue: false,
      reviewedAt: new Date("2026-11-05T12:00:00Z"),
      stateBefore: before,
      stateAfter: after,
      replacesReviewId: "r0",
    });

    expect(db.select().from(schema.reviews).get()).toMatchObject({ wasDue: 0, replacesReviewId: "r0" });
    expect(outboxEntries(db)[0].payload).toMatchObject({ was_due: false, replaces_review_id: "r0" });
  });

  it("dropCard deletes the card and sends its id", () => {
    const db = makeTestDb();
    seedCard(db, {});

    dropCard(db, "c1");

    expect(cardById(db, "c1")?.deletedAt).not.toBeNull();
    expect(outboxEntries(db)).toEqual([{ type: "drop_card", payload: { id: "c1" } }]);
  });

  it("setCardsOff(true) turns the source's cards off and deletes only its live cards", () => {
    const db = makeTestDb();
    seedSource(db, { id: "s1" });
    seedSource(db, { id: "s2" });
    seedCard(db, { id: "live" });
    seedCard(db, { id: "gone", deletedAt: "2026-11-02T00:00:00Z" });
    seedCard(db, { id: "other", sourceId: "s2" });

    setCardsOff(db, "s1", true);

    expect(sourceById(db, "s1")?.cardsOff).toBe(1);
    expect(cardById(db, "live")?.deletedAt).not.toBeNull();
    expect(cardById(db, "gone")?.deletedAt).toBe("2026-11-02T00:00:00Z");
    expect(cardById(db, "other")?.deletedAt).toBeNull();
    expect(outboxEntries(db)).toEqual([{ type: "set_cards_off", payload: { id: "s1", off: true } }]);
  });

  it("setCardsOff(false) turns cards back on and shows the source processing while analyze re-runs", () => {
    const db = makeTestDb();
    seedSource(db, { id: "s1", cardsOff: 1, processing: "failed", processingError: "boom" });

    setCardsOff(db, "s1", false);

    expect(sourceById(db, "s1")).toMatchObject({ cardsOff: 0, processing: "processing", processingError: null });
    expect(outboxEntries(db)).toEqual([{ type: "set_cards_off", payload: { id: "s1", off: false } }]);
  });

  it("requestNewsQuiz only queues the week's request", () => {
    const db = makeTestDb();
    seedSource(db, {});
    seedCard(db, {});

    requestNewsQuiz(db, "2026-11-01");

    expect(outboxEntries(db)).toEqual([{ type: "request_news_quiz", payload: { week_start: "2026-11-01" } }]);
    expect(sourceById(db, "s1")?.updatedAt).toBe("2026-11-01T00:00:00Z");
    expect(cardById(db, "c1")).toMatchObject({ deletedAt: null, fsrsState: "new" });
  });
});
