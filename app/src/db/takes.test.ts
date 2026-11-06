import { asc, eq } from "drizzle-orm";

import { changeTakeKind, deleteTake, restoreTakeVersion, retryTakeCleanup, saveTake } from "./actions";
import type { AppDb } from "./client";
import * as schema from "./schema";
import { makeTestDb } from "./testDb";

// expo-crypto is a native module; node's crypto gives the same UUIDs.
jest.mock("expo-crypto", () => ({ randomUUID: () => require("crypto").randomUUID() }));

const outbox = (db: AppDb) =>
  db.select().from(schema.outbox).all().map((entry) => ({ type: entry.type, payload: JSON.parse(entry.payload) }));
const take = (db: AppDb, id: string) => db.select().from(schema.takes).where(eq(schema.takes.id, id)).get();
const versions = (db: AppDb, takeId: string) =>
  db
    .select()
    .from(schema.takeVersions)
    .where(eq(schema.takeVersions.takeId, takeId))
    .orderBy(asc(schema.takeVersions.version))
    .all();

const BODY = "Stablecoins settle ~$10T a year.";

function writeTake(db: AppDb, overrides: Partial<Parameters<typeof saveTake>[1]> = {}): string {
  return saveTake(db, { id: null, kind: "talking_point", title: "The argument for crypto", body: BODY, clean: false, ...overrides });
}

function insertCard(db: AppDb, values: { id: string; sourceId?: string | null; takeId?: string | null }): void {
  db.insert(schema.cards)
    .values({ kind: "take", question: "Q?", answer: "A.", createdAt: "x", sourceId: null, ...values })
    .run();
}

describe("saveTake", () => {
  it("writes a new take with version 1, whitespace collapsed, and queues save_take", () => {
    const db = makeTestDb();

    const id = writeTake(db, { title: "  The argument   for crypto ", body: ` ${BODY} ` });

    expect(take(db, id)).toMatchObject({
      kind: "talking_point",
      title: "The argument for crypto",
      currentVersion: 1,
      deletedAt: null,
    });
    const [version] = versions(db, id);
    expect(versions(db, id)).toHaveLength(1);
    expect(version).toMatchObject({ version: 1, body: BODY, rawBody: BODY, cleaned: 0, cleanFailed: 0 });
    expect(outbox(db)).toEqual([
      {
        type: "save_take",
        payload: {
          id,
          version_id: version.id,
          kind: "talking_point",
          title: "The argument for crypto",
          body: BODY,
          clean: false,
        },
      },
    ]);
    // A take is never a source.
    expect(db.select().from(schema.sources).all()).toEqual([]);
  });

  it("with Clean it up, leaves the body empty until the cleaned version arrives", () => {
    const db = makeTestDb();

    const id = writeTake(db, { clean: true });

    expect(versions(db, id)).toEqual([expect.objectContaining({ body: null, rawBody: BODY, cleaned: 1 })]);
  });

  it("cuts a long title to 200 code points", () => {
    const db = makeTestDb();

    const id = writeTake(db, { title: "x".repeat(199) + "😀😀" });

    expect(take(db, id)?.title).toBe("x".repeat(199) + "😀");
  });

  it("renames without a new version when the body is the same", () => {
    const db = makeTestDb();
    const id = writeTake(db);

    saveTake(db, { id, kind: "opinion", title: "Crypto, actually", body: BODY, clean: false });

    expect(take(db, id)).toMatchObject({ kind: "opinion", title: "Crypto, actually", currentVersion: 1 });
    expect(versions(db, id)).toHaveLength(1);
    const saves = outbox(db);
    expect(saves.map((entry) => entry.type)).toEqual(["save_take", "save_take"]);
    // The second save's version id names no row: the server won't make one either.
    expect(db.select().from(schema.takeVersions).where(eq(schema.takeVersions.id, saves[1].payload.version_id)).get()).toBeUndefined();
  });

  it("makes version 2 for a changed body and keeps the take's cards until the server replaces them", () => {
    const db = makeTestDb();
    const id = writeTake(db);
    insertCard(db, { id: "c1", takeId: id });

    saveTake(db, { id, kind: "talking_point", title: "The argument for crypto", body: "Changed.", clean: false });

    expect(take(db, id)?.currentVersion).toBe(2);
    expect(versions(db, id).map((version) => [version.version, version.body])).toEqual([
      [1, BODY],
      [2, "Changed."],
    ]);
    expect(db.select().from(schema.cards).get()?.deletedAt).toBeNull();
  });
});

describe("the other take actions", () => {
  it("restoreTakeVersion copies an earlier version as the newest", () => {
    const db = makeTestDb();
    const id = writeTake(db, { body: "raw", clean: true });
    db.update(schema.takeVersions).set({ body: "Cleaned." }).run();
    saveTake(db, { id, kind: "talking_point", title: "T", body: "Second.", clean: false });

    restoreTakeVersion(db, id, 1);

    const third = versions(db, id)[2];
    expect(third).toMatchObject({ version: 3, body: "Cleaned.", rawBody: "raw", cleaned: 1, cleanFailed: 0 });
    expect(take(db, id)?.currentVersion).toBe(3);
    expect(outbox(db).at(-1)).toEqual({
      type: "restore_take_version",
      payload: { id, version: 1, version_id: third.id },
    });
  });

  it("restoreTakeVersion of a version that never got a body copies the raw text", () => {
    const db = makeTestDb();
    const id = writeTake(db, { body: "raw", clean: true });

    restoreTakeVersion(db, id, 1);

    expect(versions(db, id)[1]).toMatchObject({ version: 2, body: "raw", rawBody: "raw", cleaned: 1 });
  });

  it("restoreTakeVersion of a missing version does nothing", () => {
    const db = makeTestDb();
    const id = writeTake(db);

    restoreTakeVersion(db, id, 7);

    expect(versions(db, id)).toHaveLength(1);
    expect(outbox(db)).toHaveLength(1);
  });

  it("changeTakeKind queues update_take", () => {
    const db = makeTestDb();
    const id = writeTake(db);

    changeTakeKind(db, id, "opinion");

    expect(take(db, id)?.kind).toBe("opinion");
    expect(outbox(db).at(-1)).toEqual({ type: "update_take", payload: { id, kind: "opinion" } });
  });

  it("deleteTake retires its live cards and leaves a source's alone", () => {
    const db = makeTestDb();
    const id = writeTake(db);
    insertCard(db, { id: "take-card", takeId: id });
    insertCard(db, { id: "source-card", sourceId: "s1" });

    deleteTake(db, id);

    expect(take(db, id)?.deletedAt).not.toBeNull();
    const card = (cardId: string) => db.select().from(schema.cards).where(eq(schema.cards.id, cardId)).get();
    expect(card("take-card")?.deletedAt).not.toBeNull();
    expect(card("source-card")?.deletedAt).toBeNull();
    expect(outbox(db).at(-1)).toEqual({ type: "update_take", payload: { id, deleted: true } });
  });

  it("retryTakeCleanup empties a failed version's body until the cleaned one arrives", () => {
    const db = makeTestDb();
    const id = writeTake(db, { body: "raw", clean: true });
    const versionId = versions(db, id)[0].id;
    db.update(schema.takeVersions).set({ body: "raw", cleanFailed: 1 }).run();

    retryTakeCleanup(db, id, versionId);

    expect(versions(db, id)[0]).toMatchObject({ body: null, cleanFailed: 0 });
    expect(outbox(db).at(-1)).toEqual({ type: "retry_take_cleanup", payload: { id, version_id: versionId } });
  });
});
