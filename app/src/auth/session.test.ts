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
  // The app's real schema; makeTestDb only imports the client's type, so requiring it here doesn't recurse.
  const testDb = require("@/db/testDb").makeTestDb();
  return {
    db: testDb,
    seedSyncState: () => testDb.insert(require("@/db/schema").syncState).values({ id: 1, position: 0, lastPushFailed: 0 }).run(),
  };
});

import { db } from "@/db/client";
import * as SecureStore from "expo-secure-store";

import { LAST_COLLECTION_KEY, SHARED_COLLECTIONS_KEY } from "@/collections/sharedCollections";

import { KEYCHAIN_KEY, LEGACY_KEYCHAIN_GROUP, SHARED_KEYCHAIN_GROUP } from "./keychain";
import { clearSession, getSessionKey, migrateSessionKeyToSharedGroup, setSessionKey } from "./session";

const SHARED_SLOT = `${SHARED_KEYCHAIN_GROUP}/${KEYCHAIN_KEY}`;
const LEGACY_SLOT = `${LEGACY_KEYCHAIN_GROUP}/${KEYCHAIN_KEY}`;
const COLLECTIONS_SLOT = `${SHARED_KEYCHAIN_GROUP}/${SHARED_COLLECTIONS_KEY}`;
const LAST_COLLECTION_SLOT = `${SHARED_KEYCHAIN_GROUP}/${LAST_COLLECTION_KEY}`;

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
    expect(mockKeychain.has(LEGACY_SLOT)).toBe(false);
  });

  it("a stale legacy key is not migrated back after sign-out", async () => {
    mockKeychain.set(SHARED_SLOT, "key-1");
    mockKeychain.set(LEGACY_SLOT, "stale-m1-key");

    await clearSession();
    await migrateSessionKeyToSharedGroup();

    expect(mockKeychain.has(SHARED_SLOT)).toBe(false);
    expect(mockKeychain.has(LEGACY_SLOT)).toBe(false);
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
    db.insert(schema.artifacts).values({ id: "a1", sourceId: "s1", kind: "summary", version: 1, content: "{}", isCurrent: 1, createdAt: "x" }).run();
    db.insert(schema.cards).values({ id: "c1", sourceId: "s1", kind: "qa", question: "q", answer: "a", createdAt: "x" }).run();
    db.insert(schema.topics).values({ id: "t1", domain: "AI", name: "Evals", origin: "user", createdAt: "x", updatedAt: "x" }).run();
    db.insert(schema.topicPrimers).values({ id: "p1", topicId: "t1", version: 1, isCurrent: 1, content: "{}", createdAt: "x" }).run();
    db.insert(schema.collections).values({ id: "col1", name: "Bears hype", position: 0, createdAt: "x", updatedAt: "x" }).run();
    db.insert(schema.collectionItems).values({ id: "i1", collectionId: "col1", url: "u", kind: "x", createdAt: "x", updatedAt: "x" }).run();
    db.insert(schema.takes).values({ id: "k1", kind: "opinion", title: "T", currentVersion: 1, createdAt: "x", updatedAt: "x" }).run();
    db.insert(schema.takeVersions).values({ id: "v1", takeId: "k1", version: 1, body: "b", rawBody: "b", cleaned: 0, createdAt: "x" }).run();
    mockKeychain.set(COLLECTIONS_SLOT, '[{"id":"col1","name":"Bears hype"}]');
    mockKeychain.set(LAST_COLLECTION_SLOT, "col1");
  });

  it("bumps the epoch, revokes the session with the current key, then deletes the keychain item and wipes", async () => {
    const before = getSessionEpoch();

    await clearSession();

    expect(getSessionEpoch()).toBe(before + 1);
    expect(mockCalls).toEqual(["/auth/logout:key-1", "keychain-delete", "keychain-delete", "keychain-delete", "keychain-delete"]);
    expect(mockKeychain.has(SHARED_SLOT)).toBe(false);
    // The share extension's collection list and last pick go with the account.
    expect(mockKeychain.has(COLLECTIONS_SLOT)).toBe(false);
    expect(mockKeychain.has(LAST_COLLECTION_SLOT)).toBe(false);
    expect(db.select().from(schema.sources).all()).toEqual([]);
    expect(db.select().from(schema.artifacts).all()).toEqual([]);
    expect(db.select().from(schema.cards).all()).toEqual([]);
    // Topics too: the next account's picker gate reads an empty local topics table.
    expect(db.select().from(schema.topics).all()).toEqual([]);
    expect(db.select().from(schema.topicPrimers).all()).toEqual([]);
    expect(db.select().from(schema.collections).all()).toEqual([]);
    expect(db.select().from(schema.collectionItems).all()).toEqual([]);
    expect(db.select().from(schema.takes).all()).toEqual([]);
    expect(db.select().from(schema.takeVersions).all()).toEqual([]);
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
