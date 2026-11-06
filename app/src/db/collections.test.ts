import { eq } from "drizzle-orm";

import {
  addCollectionItem,
  createCollection,
  deleteCollection,
  editCollectionItemNote,
  moveCollectionItem,
  removeCollectionItem,
  renameCollection,
} from "./actions";
import type { AppDb } from "./client";
import * as schema from "./schema";
import { makeTestDb } from "./testDb";

// expo-crypto is a native module; node's crypto gives the same UUIDs.
jest.mock("expo-crypto", () => ({ randomUUID: () => require("crypto").randomUUID() }));

const outbox = (db: AppDb) =>
  db.select().from(schema.outbox).all().map((entry) => ({ type: entry.type, payload: JSON.parse(entry.payload) }));
const collection = (db: AppDb, id: string) =>
  db.select().from(schema.collections).where(eq(schema.collections.id, id)).get();
const item = (db: AppDb, id: string) =>
  db.select().from(schema.collectionItems).where(eq(schema.collectionItems.id, id)).get();

describe("collections", () => {
  it("makes collections at the end, with whitespace collapsed, and queues create_collection", () => {
    const db = makeTestDb();

    const first = createCollection(db, "  Bears   hype ");
    const second = createCollection(db, "Funny");

    expect(collection(db, first)).toMatchObject({ name: "Bears hype", position: 0, deletedAt: null });
    expect(collection(db, second)?.position).toBe(1);
    expect(outbox(db)).toEqual([
      { type: "create_collection", payload: { id: first, name: "Bears hype" } },
      { type: "create_collection", payload: { id: second, name: "Funny" } },
    ]);
  });

  it("cuts a long name to 100 characters so the server accepts it", () => {
    const db = makeTestDb();

    const id = createCollection(db, "x".repeat(150));

    expect(collection(db, id)?.name).toHaveLength(100);
  });

  it("saves a post as a pending link that is never a source", () => {
    const db = makeTestDb();
    const collectionId = createCollection(db, "Bears hype");

    const itemId = addCollectionItem(db, { collectionId, url: "https://x.com/a/status/1" });

    expect(item(db, itemId)).toMatchObject({ collectionId, kind: "link", metadataStatus: "pending", note: null });
    expect(db.select().from(schema.sources).all()).toEqual([]);
    expect(outbox(db).at(-1)).toEqual({
      type: "add_collection_item",
      payload: { id: itemId, collection_id: collectionId, url: "https://x.com/a/status/1" },
    });
  });

  it("deleting a collection soft-deletes its posts and queues one update_collection", () => {
    const db = makeTestDb();
    const collectionId = createCollection(db, "Bears hype");
    const itemId = addCollectionItem(db, { collectionId, url: "https://example.com/a" });

    deleteCollection(db, collectionId);

    expect(collection(db, collectionId)?.deletedAt).not.toBeNull();
    expect(item(db, itemId)?.deletedAt).not.toBeNull();
    expect(outbox(db).at(-1)).toEqual({ type: "update_collection", payload: { id: collectionId, deleted: true } });
  });

  it("renames, edits a note (blank clears it), moves and removes", () => {
    const db = makeTestDb();
    const first = createCollection(db, "Bears hype");
    const second = createCollection(db, "Funny");
    const itemId = addCollectionItem(db, { collectionId: first, url: "https://example.com/a" });

    renameCollection(db, first, " Bears  film room ");
    editCollectionItemNote(db, itemId, " the scramble ");
    const noted = item(db, itemId)?.note;
    editCollectionItemNote(db, itemId, "   ");
    moveCollectionItem(db, itemId, second);
    removeCollectionItem(db, itemId);

    expect(collection(db, first)?.name).toBe("Bears film room");
    expect(noted).toBe("the scramble");
    expect(item(db, itemId)).toMatchObject({ note: null, collectionId: second });
    expect(item(db, itemId)?.deletedAt).not.toBeNull();
    expect(outbox(db).slice(-5)).toEqual([
      { type: "update_collection", payload: { id: first, name: "Bears film room" } },
      { type: "update_collection_item", payload: { id: itemId, note: "the scramble" } },
      { type: "update_collection_item", payload: { id: itemId, note: null } },
      { type: "update_collection_item", payload: { id: itemId, collection_id: second } },
      { type: "update_collection_item", payload: { id: itemId, deleted: true } },
    ]);
  });
});
