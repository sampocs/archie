import Database from "better-sqlite3";
import { drizzle } from "drizzle-orm/better-sqlite3";

import { addSource } from "./actions";
import type { AppDb } from "./client";
import * as schema from "./schema";

// expo-crypto is a native module; node's crypto gives the same UUIDs.
jest.mock("expo-crypto", () => ({ randomUUID: () => require("crypto").randomUUID() }));

function createTables(outboxCheck: string): string {
  return `
    CREATE TABLE sources (
      id text PRIMARY KEY NOT NULL, url text NOT NULL, title text, kind text NOT NULL, state text NOT NULL,
      intent text NOT NULL, created_at text NOT NULL, updated_at text NOT NULL, deleted_at text, sync_error text
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
  });

  it("leaves no source row behind when the outbox insert throws", async () => {
    const db = makeDb("add_source");

    await expect(addSource(db, { url: "https://example.com/b", intent: "finished" })).rejects.toThrow();

    expect(db.select().from(schema.sources).all()).toHaveLength(0);
    expect(db.select().from(schema.outbox).all()).toHaveLength(0);
  });
});
