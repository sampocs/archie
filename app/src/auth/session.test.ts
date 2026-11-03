import * as schema from "@/db/schema";

import { getSessionEpoch } from "./sessionEpoch";

const mockCalls: string[] = [];
let mockLogout: () => Promise<unknown> = async () => null;

jest.mock("expo-apple-authentication", () => ({}));
// An in-memory Keychain keyed by access group, like the real one: a lookup only sees its own group.
const mockKeychain = new Map<string, string>();
const slot = (key: string, options?: { accessGroup?: string }) => `${options?.accessGroup ?? "none"}/${key}`;

jest.mock("expo-secure-store", () => ({
  getItemAsync: jest.fn(async (key: string, options?: { accessGroup?: string }) => mockKeychain.get(slot(key, options)) ?? null),
  setItemAsync: jest.fn(async (key: string, value: string, options?: { accessGroup?: string }) => {
    mockKeychain.set(slot(key, options), value);
  }),
  deleteItemAsync: jest.fn(async (key: string, options?: { accessGroup?: string }) => {
    mockCalls.push("keychain-delete");
    mockKeychain.delete(slot(key, options));
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
import * as SecureStore from "expo-secure-store";

import { KEYCHAIN_KEY, LEGACY_KEYCHAIN_GROUP, SHARED_KEYCHAIN_GROUP } from "./keychain";
import { clearSession, getSessionKey, migrateSessionKeyToSharedGroup, setSessionKey } from "./session";

const SHARED_SLOT = `${SHARED_KEYCHAIN_GROUP}/${KEYCHAIN_KEY}`;
const LEGACY_SLOT = `${LEGACY_KEYCHAIN_GROUP}/${KEYCHAIN_KEY}`;

describe("shared Keychain group", () => {
  beforeEach(() => {
    mockKeychain.clear();
    mockCalls.length = 0;
  });

  it("stores and reads the session key in the shared group", async () => {
    await setSessionKey("key-2");

    expect(mockKeychain.get(SHARED_SLOT)).toBe("key-2");
    expect(await getSessionKey()).toBe("key-2");
  });

  it("migration copies an M1 key into the group and removes the old one", async () => {
    mockKeychain.set(LEGACY_SLOT, "m1-key");

    await migrateSessionKeyToSharedGroup();

    expect(mockKeychain.get(SHARED_SLOT)).toBe("m1-key");
    expect(mockKeychain.has(LEGACY_SLOT)).toBe(false);
  });

  it("migration runs once: a second run does not touch the keychain", async () => {
    mockKeychain.set(LEGACY_SLOT, "m1-key");
    await migrateSessionKeyToSharedGroup();
    (SecureStore.setItemAsync as jest.Mock).mockClear();
    (SecureStore.deleteItemAsync as jest.Mock).mockClear();

    await migrateSessionKeyToSharedGroup();

    expect(SecureStore.setItemAsync).not.toHaveBeenCalled();
    expect(SecureStore.deleteItemAsync).not.toHaveBeenCalled();
    expect(mockKeychain.get(SHARED_SLOT)).toBe("m1-key");
  });

  it("migration never overwrites a key already in the group", async () => {
    mockKeychain.set(SHARED_SLOT, "new-key");
    mockKeychain.set(LEGACY_SLOT, "stale-m1-key");

    await migrateSessionKeyToSharedGroup();

    expect(mockKeychain.get(SHARED_SLOT)).toBe("new-key");
    expect(mockKeychain.get(LEGACY_SLOT)).toBe("stale-m1-key");
  });

  it("migration does nothing when there is no key anywhere", async () => {
    await migrateSessionKeyToSharedGroup();

    expect(mockKeychain.size).toBe(0);
  });
});

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
    expect(mockKeychain.has(SHARED_SLOT)).toBe(false);
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
