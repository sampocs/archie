import * as schema from "@/db/schema";

import { getSessionEpoch } from "./sessionEpoch";

const mockCalls: string[] = [];
let mockLogout: () => Promise<unknown> = async () => null;

jest.mock("expo-apple-authentication", () => ({}));
jest.mock("expo-secure-store", () => ({
  getItemAsync: jest.fn(async () => "key-1"),
  setItemAsync: jest.fn(async () => undefined),
  deleteItemAsync: jest.fn(async () => {
    mockCalls.push("keychain-delete");
  }),
}));
jest.mock("@/api/client", () => ({
  apiFetch: jest.fn(async (path: string, init: { sessionKey: string | null }) => {
    mockCalls.push(`${path}:${init.sessionKey}`);
    return mockLogout();
  }),
}));
jest.mock("@/db/client", () => {
  const sqlite = new (require("better-sqlite3"))(":memory:");
  sqlite.exec(`
    CREATE TABLE sources (id text PRIMARY KEY NOT NULL, url text NOT NULL, title text, kind text NOT NULL, state text NOT NULL,
      intent text NOT NULL, created_at text NOT NULL, updated_at text NOT NULL, deleted_at text, sync_error text,
      processing text DEFAULT 'pending' NOT NULL, processing_error text, reaction text, note text,
      prep_me integer DEFAULT 0 NOT NULL, merged_into_id text);
    CREATE TABLE outbox (id text PRIMARY KEY NOT NULL, type text NOT NULL, payload text NOT NULL, created_at text NOT NULL,
      status text NOT NULL, error text);
    CREATE TABLE sync_state (id integer PRIMARY KEY NOT NULL, position integer NOT NULL, last_push_failed integer NOT NULL);
  `);
  const testDb = require("drizzle-orm/better-sqlite3").drizzle(sqlite, { schema: require("@/db/schema") });
  return {
    db: testDb,
    seedSyncState: () => testDb.insert(require("@/db/schema").syncState).values({ id: 1, position: 0, lastPushFailed: 0 }).run(),
  };
});

import { db } from "@/db/client";
import { clearSession, setSessionKey } from "./session";


describe("clearSession", () => {
  beforeEach(async () => {
    mockLogout = async () => null;
    await setSessionKey("key-1");
    mockCalls.length = 0;
    db.insert(schema.sources).values({ id: "s1", url: "u", kind: "link", state: "queued", intent: "queue", createdAt: "x", updatedAt: "x" }).run();
  });

  it("bumps the epoch, revokes the session with the current key, then deletes the keychain item and wipes", async () => {
    const before = getSessionEpoch();

    await clearSession();

    expect(getSessionEpoch()).toBe(before + 1);
    expect(mockCalls).toEqual(["/auth/logout:key-1", "keychain-delete"]);
    expect(db.select().from(schema.sources).all()).toEqual([]);
    expect(db.select().from(schema.syncState).get()).toMatchObject({ position: 0 });
  });

  it("still signs out locally when the logout request fails (offline)", async () => {
    mockLogout = async () => {
      throw new Error("offline");
    };

    await clearSession();

    expect(mockCalls).toContain("keychain-delete");
    expect(db.select().from(schema.sources).all()).toEqual([]);
  });

  it("bumps the epoch before the network call, so in-flight syncs stop at once", async () => {
    const before = getSessionEpoch();
    let epochDuringLogout = -1;
    mockLogout = async () => {
      epochDuringLogout = getSessionEpoch();
      return null;
    };

    await clearSession();

    expect(epochDuringLogout).toBe(before + 1);
  });
});
