import Database from "better-sqlite3";
import { drizzle } from "drizzle-orm/better-sqlite3";
import { eq } from "drizzle-orm";

import { addSource, retrySource } from "./actions";
import type { AppDb } from "./client";
import * as schema from "./schema";

// expo-crypto is a native module; node's crypto gives the same UUIDs.
jest.mock("expo-crypto", () => ({ randomUUID: () => require("crypto").randomUUID() }));

function createTables(outboxCheck: string): string {
  return `
    CREATE TABLE sources (
      id text PRIMARY KEY NOT NULL, url text NOT NULL, title text, kind text NOT NULL, state text NOT NULL,
      intent text NOT NULL, created_at text NOT NULL, updated_at text NOT NULL, deleted_at text, sync_error text,
      processing text DEFAULT 'pending' NOT NULL, processing_error text, reaction text, note text,
      prep_me integer DEFAULT 0 NOT NULL, merged_into_id text, sender text
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
