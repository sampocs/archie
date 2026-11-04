import Database from "better-sqlite3";
import { drizzle } from "drizzle-orm/better-sqlite3";
import { eq } from "drizzle-orm";

import {
  addSource,
  addTopic,
  chooseTopics,
  finishSource,
  goDeeper,
  mergeTopic,
  readLater,
  removeTopic,
  retrySource,
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
      prep_me integer DEFAULT 0 NOT NULL, merged_into_id text, sender text, domain text, topic_id text,
      image_url text, queue_position real, read_at text, snoozed_until text, primer_opened_at text, newsletter_kind text
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
    expect(sourceRows[0]).toMatchObject({ processing: "pending", reaction: null, note: null, prepMe: 0 });
  });

  it("sends reaction and note for a finished source, and prep_me for a queued one, in snake_case", async () => {
    const db = makeDb();

    const finishedId = await addSource(db, {
      url: "https://example.com/f",
      intent: "finished",
      reaction: "lost",
      note: "the second half",
    });
    const queuedId = await addSource(db, { url: "https://example.com/q", intent: "queue", prepMe: true });

    const payloads = db.select().from(schema.outbox).all().map((row) => JSON.parse(row.payload));
    expect(payloads).toContainEqual({
      id: finishedId,
      url: "https://example.com/f",
      intent: "finished",
      reaction: "lost",
      note: "the second half",
    });
    expect(payloads).toContainEqual({ id: queuedId, url: "https://example.com/q", intent: "queue", prep_me: true });
    expect(db.select().from(schema.sources).where(eq(schema.sources.id, queuedId)).get()?.prepMe).toBe(1);
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

describe("finishSource", () => {
  it("marks a lost source consumed and prepped, and leaves an empty note out of the payload", () => {
    const db = makeTestDb();
    seedSource(db, { snoozedUntil: "2026-11-09T14:00:00.000Z" });

    finishSource(db, { sourceId: "s1", reaction: "lost", note: null });

    expect(sourceById(db, "s1")).toMatchObject({ state: "consumed", reaction: "lost", prepMe: 1, snoozedUntil: null });
    expect(outboxEntries(db)).toEqual([{ type: "finish_source", payload: { id: "s1", reaction: "lost" } }]);
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
