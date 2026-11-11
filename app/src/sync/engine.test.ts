import Database from "better-sqlite3";
import { eq, sql } from "drizzle-orm";

import migrations from "../../drizzle/migrations";
import {
  addCollectionItem,
  changeTakeKind,
  createCollection,
  dropCard,
  editCollectionItemNote,
  goDeeper,
  queuePrimer,
  removeCollectionItem,
  renameCollection,
  requestPrimer,
  restoreTakeVersion,
  retryTakeCleanup,
  returnToInbox,
  reviewCard,
  saveTake,
  setCardsOff,
  setFavorite,
  snooze,
} from "@/db/actions";

import { ClientError, NetworkError, UnauthorizedError } from "@/api/client";
import type { AppDb } from "@/db/client";
import * as schema from "@/db/schema";
import { makeTestDb } from "@/db/testDb";

import {
  createSyncScheduler,
  OutboxEntry,
  PulledArtifact,
  PulledCard,
  PulledCollection,
  PulledCollectionItem,
  PulledSource,
  PulledTake,
  PulledTakeVersion,
  PulledTopic,
  PulledTopicPrimer,
  PullPage,
  PushResult,
  runSync,
  SyncStore,
  SyncTransport,
} from "./engine";
import { bumpSessionEpoch, getSessionEpoch } from "@/auth/sessionEpoch";
import { createDbSyncStore } from "./transport";

jest.mock("expo-crypto", () => ({
  randomUUID: () => require("crypto").randomUUID(),
}));

// In-memory store: a plain object over arrays.
function makeMemoryStore(pending: OutboxEntry[], position = 0) {
  const state = {
    pending: [...pending],
    rejected: [] as { id: string; reason: string }[],
    position,
    applied: [] as PullPage[],
    failedFlags: [] as boolean[],
  };
  const store: SyncStore = {
    async pendingActions(limit) {
      return state.pending.slice(0, limit);
    },
    async removeActions(ids) {
      state.pending = state.pending.filter((entry) => !ids.includes(entry.id));
    },
    async rejectAction(id, reason) {
      state.rejected.push({ id, reason });
      state.pending = state.pending.filter((entry) => entry.id !== id);
    },
    async getPosition() {
      return state.position;
    },
    async applyPage(page) {
      state.applied.push(page);
      state.position = page.position;
    },
    async setLastPushFailed(failed) {
      state.failedFlags.push(failed);
    },
  };
  return { store, state };
}

function makeEntries(count: number): OutboxEntry[] {
  return Array.from({ length: count }, (_, index) => ({
    id: `a${index}`,
    type: "add_source",
    payload: {},
  }));
}

const emptyPage = (position: number, more = false): PullPage => ({
  rows: {
    sources: [],
    artifacts: [],
    cards: [],
    topics: [],
    topic_primers: [],
  },
  position,
  more,
});

function makeTransport(overrides: Partial<SyncTransport> = {}) {
  const calls = { pushes: [] as string[][], pulls: [] as number[] };
  const transport: SyncTransport = {
    async push(actions) {
      calls.pushes.push(actions.map((entry) => entry.id));
      return actions.map((entry): PushResult => ({
        id: entry.id,
        result: "applied",
        reason: null,
      }));
    },
    async pull(since) {
      calls.pulls.push(since);
      return emptyPage(since);
    },
    ...overrides,
  };
  return { transport, calls };
}

describe("runSync push", () => {
  it("pushes in creation order in batches of 50 and removes applied and duplicate entries", async () => {
    const { store, state } = makeMemoryStore(makeEntries(120));
    const { transport, calls } = makeTransport({
      async push(actions) {
        calls.pushes.push(actions.map((entry) => entry.id));
        return actions.map((entry, index): PushResult => ({
          id: entry.id,
          result: index % 2 === 0 ? "applied" : "duplicate",
          reason: null,
        }));
      },
    });

    const outcome = await runSync(store, transport);

    expect(outcome).toBe("synced");
    expect(calls.pushes.map((batch) => batch.length)).toEqual([50, 50, 20]);
    expect(calls.pushes.flat()).toEqual(
      makeEntries(120).map((entry) => entry.id),
    );
    expect(state.pending).toEqual([]);
  });

  it("records a rejection with its reason and still removes the rest of the batch", async () => {
    const { store, state } = makeMemoryStore(makeEntries(3));
    const { transport } = makeTransport({
      async push(actions) {
        return actions.map((entry): PushResult =>
          entry.id === "a1"
            ? { id: entry.id, result: "rejected", reason: "unsupported url" }
            : { id: entry.id, result: "applied", reason: null },
        );
      },
    });

    await runSync(store, transport);

    expect(state.rejected).toEqual([{ id: "a1", reason: "unsupported url" }]);
    expect(state.pending).toEqual([]);
  });

  it("goes offline on a push NetworkError: flags the failure, keeps every action and does not pull", async () => {
    const { store, state } = makeMemoryStore(makeEntries(3));
    const { transport, calls } = makeTransport({
      async push() {
        throw new NetworkError("down");
      },
    });

    const outcome = await runSync(store, transport);

    expect(outcome).toBe("offline");
    expect(state.failedFlags).toEqual([true]);
    expect(state.pending).toHaveLength(3);
    expect(calls.pulls).toEqual([]);
  });

  it("treats a refused push (4xx) as a failed push: flags it, keeps the actions and goes offline", async () => {
    const { store, state } = makeMemoryStore(makeEntries(2));
    const { transport, calls } = makeTransport({
      async push() {
        throw new ClientError("422");
      },
    });

    expect(await runSync(store, transport)).toBe("offline");
    expect(state.failedFlags).toEqual([true]);
    expect(state.pending).toHaveLength(2);
    expect(calls.pulls).toEqual([]);
  });

  it("still throws a refused pull (4xx) without flagging a failed push", async () => {
    const { store, state } = makeMemoryStore([]);
    const { transport } = makeTransport({
      async pull() {
        throw new ClientError("400");
      },
    });

    await expect(runSync(store, transport)).rejects.toBeInstanceOf(ClientError);
    expect(state.failedFlags).toEqual([false]);
  });

  it("throws instead of re-sending forever when no result belongs to the pushed batch", async () => {
    const { store } = makeMemoryStore(makeEntries(2));
    const { transport } = makeTransport({
      async push() {
        return [{ id: "unrelated", result: "applied", reason: null }];
      },
    });

    await expect(runSync(store, transport)).rejects.toThrow(
      "no results for the pushed batch",
    );
  });

  it("clears lastPushFailed after a successful push", async () => {
    const { store, state } = makeMemoryStore(makeEntries(1));
    const { transport } = makeTransport();

    await runSync(store, transport);

    expect(state.failedFlags).toEqual([false]);
  });

  it("reports a push through onPushed, and stays silent when there was nothing to push", async () => {
    const pushed = jest.fn();
    const withActions = makeMemoryStore(makeEntries(2));
    await runSync(withActions.store, makeTransport().transport, pushed);
    expect(pushed).toHaveBeenCalledTimes(1);

    pushed.mockClear();
    const empty = makeMemoryStore([]);
    await runSync(empty.store, makeTransport().transport, pushed);
    expect(pushed).not.toHaveBeenCalled();
  });

  it("does not report a push that never reached the server", async () => {
    const pushed = jest.fn();
    const { store } = makeMemoryStore(makeEntries(1));
    const { transport } = makeTransport({
      async push() {
        throw new NetworkError("down");
      },
    });

    await runSync(store, transport, pushed);

    expect(pushed).not.toHaveBeenCalled();
  });

  it("returns unauthorized when push is rejected with 401", async () => {
    const { store } = makeMemoryStore(makeEntries(1));
    const { transport } = makeTransport({
      async push() {
        throw new UnauthorizedError("401");
      },
    });

    expect(await runSync(store, transport)).toBe("unauthorized");
  });
});

describe("runSync pull", () => {
  it("pushes first, then pulls from the stored position following `more` and saves the final position", async () => {
    const { store, state } = makeMemoryStore(makeEntries(1), 7);
    const order: string[] = [];
    const pages = [
      emptyPage(10, true),
      emptyPage(20, true),
      emptyPage(25, false),
    ];
    const { transport, calls } = makeTransport({
      async push(actions) {
        order.push("push");
        return actions.map((entry): PushResult => ({
          id: entry.id,
          result: "applied",
          reason: null,
        }));
      },
      async pull(since) {
        order.push("pull");
        calls.pulls.push(since);
        return pages.shift() as PullPage;
      },
    });

    await runSync(store, transport);

    expect(order).toEqual(["push", "pull", "pull", "pull"]);
    expect(calls.pulls).toEqual([7, 10, 20]);
    expect(state.applied.map((page) => page.position)).toEqual([10, 20, 25]);
    expect(state.position).toBe(25);
  });

  it("returns offline on a pull NetworkError without flagging a failed push", async () => {
    const { store, state } = makeMemoryStore(makeEntries(1));
    const { transport } = makeTransport({
      async pull() {
        throw new NetworkError("down");
      },
    });

    expect(await runSync(store, transport)).toBe("offline");
    expect(state.failedFlags).toEqual([false]);
  });

  it("returns unauthorized when pull is rejected with 401", async () => {
    const { store } = makeMemoryStore([]);
    const { transport } = makeTransport({
      async pull() {
        throw new UnauthorizedError("401");
      },
    });

    expect(await runSync(store, transport)).toBe("unauthorized");
  });
});

function makeDbStore() {
  const db = makeTestDb();
  return { db, store: createDbSyncStore(db) };
}

const pulledSource = (overrides: Partial<PulledSource>): PulledSource => ({
  id: "s1",
  url: "https://example.com/a",
  title: null,
  kind: "link",
  state: "queued",
  intent: "queue",
  created_at: "2026-11-01T00:00:00Z",
  updated_at: "2026-11-01T00:00:00Z",
  deleted_at: null,
  processing: "pending",
  processing_error: null,
  reaction: null,
  note: null,
  merged_into_id: null,
  sender: null,
  domain: null,
  topic_id: null,
  image_url: null,
  queue_position: null,
  read_at: null,
  snoozed_until: null,
  primer_opened_at: null,
  primer_queue_position: null,
  primer_snoozed_until: null,
  newsletter_kind: null,
  ...overrides,
});

const pulledArtifact = (
  overrides: Partial<PulledArtifact>,
): PulledArtifact => ({
  id: "a1",
  source_id: "s1",
  kind: "summary",
  version: 1,
  content: { gist: "One line", key_ideas: ["a", "b"] },
  is_current: true,
  created_at: "2026-11-01T00:00:00Z",
  ...overrides,
});

const pulledCard = (overrides: Partial<PulledCard>): PulledCard => ({
  id: "c1",
  source_id: "s1",
  kind: "qa",
  question: "Q?",
  answer: "A.",
  created_at: "2026-11-01T00:00:00Z",
  deleted_at: null,
  ...overrides,
});

describe("database SyncStore", () => {
  it("upserts a pulled row over the local copy, keeps syncError, and saves the position", async () => {
    const { db, store } = makeDbStore();
    db.insert(schema.sources)
      .values({
        ...pulledSource({}),
        createdAt: "2026-11-01T00:00:00Z",
        updatedAt: "2026-11-01T00:00:00Z",
        syncError: "boom",
      })
      .run();

    await store.applyPage({
      rows: {
        sources: [
          pulledSource({
            title: "Server title",
            state: "consumed",
            updated_at: "2026-11-02T00:00:00Z",
          }),
        ],
        artifacts: [],
        cards: [],
        topics: [],
        topic_primers: [],
      },
      position: 42,
      more: false,
    });

    const row = db
      .select()
      .from(schema.sources)
      .where(eq(schema.sources.id, "s1"))
      .get();
    expect(row).toMatchObject({
      title: "Server title",
      state: "consumed",
      updatedAt: "2026-11-02T00:00:00Z",
      syncError: "boom",
    });
    expect(await store.getPosition()).toBe(42);
  });

  it("stores a pulled source's sender and updates it on a re-pull", async () => {
    const { db, store } = makeDbStore();
    const page = (sender: string | null) => ({
      rows: {
        sources: [pulledSource({ kind: "newsletter", state: "inbox", sender })],
        artifacts: [],
        cards: [],
        topics: [],
        topic_primers: [],
      },
      position: 1,
      more: false,
    });
    const senderOf = () =>
      db.select().from(schema.sources).where(eq(schema.sources.id, "s1")).get()
        ?.sender;

    await store.applyPage(page("Ben Thompson <ben@stratechery.com>"));
    expect(senderOf()).toBe("Ben Thompson <ben@stratechery.com>");

    await store.applyPage(page("Stratechery"));
    expect(senderOf()).toBe("Stratechery");
  });

  it("skips rows whose source has an unsent local action but still saves the position", async () => {
    const { db, store } = makeDbStore();
    db.insert(schema.sources)
      .values({
        ...pulledSource({ title: "Local title" }),
        createdAt: "x",
        updatedAt: "x",
      })
      .run();
    db.insert(schema.outbox)
      .values({
        id: "o1",
        type: "update_source",
        payload: JSON.stringify({ id: "s1" }),
        createdAt: "x",
        status: "pending",
      })
      .run();

    await store.applyPage({
      rows: {
        sources: [
          pulledSource({ title: "Server title" }),
          pulledSource({ id: "s3", title: "Other" }),
        ],
        artifacts: [],
        cards: [],
        topics: [],
        topic_primers: [],
      },
      position: 9,
      more: false,
    });

    const rows = db.select().from(schema.sources).all();
    expect(rows.find((row) => row.id === "s1")?.title).toBe("Local title");
    expect(rows.find((row) => row.id === "s3")?.title).toBe("Other");
    expect(await store.getPosition()).toBe(9);
  });

  it("stores pulled artifacts (content as JSON text) and cards, and updates them in place on a re-pull", async () => {
    const { db, store } = makeDbStore();
    const page = (artifact: PulledArtifact, card: PulledCard): PullPage => ({
      rows: {
        sources: [
          pulledSource({
            processing: "ready",
            primer_queue_position: -2.5,
            primer_snoozed_until: "2026-11-05T14:00:00Z",
            reaction: "easy",
          }),
        ],
        artifacts: [artifact],
        cards: [card],
        topics: [],
        topic_primers: [],
      },
      position: 5,
      more: false,
    });

    await store.applyPage(page(pulledArtifact({}), pulledCard({})));

    expect(db.select().from(schema.sources).get()).toMatchObject({
      processing: "ready",
      primerQueuePosition: -2.5,
      primerSnoozedUntil: "2026-11-05T14:00:00Z",
      reaction: "easy",
    });
    const stored = db.select().from(schema.artifacts).get();
    expect(stored).toMatchObject({
      sourceId: "s1",
      kind: "summary",
      version: 1,
      isCurrent: 1,
    });
    expect(JSON.parse(stored!.content)).toEqual({
      gist: "One line",
      key_ideas: ["a", "b"],
    });
    expect(db.select().from(schema.cards).get()).toMatchObject({
      question: "Q?",
      answer: "A.",
      detail: "",
      deletedAt: null,
    });

    await store.applyPage(
      page(
        pulledArtifact({ is_current: false, content: { gist: "Newer" } }),
        pulledCard({ answer: "A2.", deleted_at: "2026-11-02T00:00:00Z" }),
      ),
    );

    expect(db.select().from(schema.artifacts).all()).toHaveLength(1);
    const updated = db.select().from(schema.artifacts).get();
    expect(updated?.isCurrent).toBe(0);
    expect(JSON.parse(updated!.content)).toEqual({ gist: "Newer" });
    expect(db.select().from(schema.cards).all()).toHaveLength(1);
    expect(db.select().from(schema.cards).get()).toMatchObject({
      answer: "A2.",
      deletedAt: "2026-11-02T00:00:00Z",
    });
  });

  it("inserts rows it has not seen and applies tombstones", async () => {
    const { db, store } = makeDbStore();

    await store.applyPage({
      rows: {
        sources: [
          pulledSource({ id: "s2", deleted_at: "2026-11-02T00:00:00Z" }),
        ],
        artifacts: [],
        cards: [],
        topics: [],
        topic_primers: [],
      },
      position: 1,
      more: false,
    });

    const row = db
      .select()
      .from(schema.sources)
      .where(eq(schema.sources.id, "s2"))
      .get();
    expect(row?.deletedAt).toBe("2026-11-02T00:00:00Z");
  });

  it("returns only pending actions oldest first, and a rejection sets the source's syncError and leaves the queue", async () => {
    const { db, store } = makeDbStore();
    const outboxRow = (
      id: string,
      createdAt: string,
      status: "pending" | "rejected",
    ) => ({
      id,
      type: "add_source",
      payload: JSON.stringify({ id: `src-${id}` }),
      createdAt,
      status,
    });
    db.insert(schema.outbox)
      .values([
        outboxRow("late", "2026-11-01T00:00:02Z", "pending"),
        outboxRow("early", "2026-11-01T00:00:01Z", "pending"),
        outboxRow("old", "2026-11-01T00:00:00Z", "rejected"),
      ])
      .run();
    db.insert(schema.sources)
      .values({
        ...pulledSource({ id: "src-early" }),
        createdAt: "x",
        updatedAt: "x",
      })
      .run();

    expect((await store.pendingActions(50)).map((entry) => entry.id)).toEqual([
      "early",
      "late",
    ]);

    await store.rejectAction("early", "bad url");

    expect((await store.pendingActions(50)).map((entry) => entry.id)).toEqual([
      "late",
    ]);
    const source = db
      .select()
      .from(schema.sources)
      .where(eq(schema.sources.id, "src-early"))
      .get();
    expect(source?.syncError).toBe("bad url");
    expect(source?.processing).toBe("pending");
  });

  it("a rejected retry_source puts the source back to failed, undoing the optimistic processing", async () => {
    const { db, store } = makeDbStore();
    db.insert(schema.sources)
      .values({
        ...pulledSource({ id: "src-1" }),
        processing: "processing",
        createdAt: "x",
        updatedAt: "x",
      })
      .run();
    db.insert(schema.outbox)
      .values({
        id: "retry",
        type: "retry_source",
        payload: JSON.stringify({ id: "src-1" }),
        createdAt: "2026-11-01T00:00:00Z",
        status: "pending",
      })
      .run();

    await store.rejectAction("retry", "source is not failed");

    const source = db
      .select()
      .from(schema.sources)
      .where(eq(schema.sources.id, "src-1"))
      .get();
    expect(source).toMatchObject({
      processing: "failed",
      syncError: "source is not failed",
    });
  });

  it("stores a pulled source's favorited_at, and a missing one as null", async () => {
    const { db, store } = makeDbStore();
    await store.applyPage({
      rows: { sources: [pulledSource({ favorited_at: "2026-11-03T00:00:00Z" })], artifacts: [], cards: [] },
      position: 1,
      more: false,
    });
    expect(sourceRow(db)?.favoritedAt).toBe("2026-11-03T00:00:00Z");

    await store.applyPage({ rows: { sources: [pulledSource({})], artifacts: [], cards: [] }, position: 2, more: false });
    expect(sourceRow(db)?.favoritedAt).toBeNull();
  });

  it("stores a pulled source's published_at, and a missing one as null", async () => {
    const { db, store } = makeDbStore();
    await store.applyPage({
      rows: { sources: [pulledSource({ published_at: "2026-11-03T10:19:36Z" })], artifacts: [], cards: [] },
      position: 1,
      more: false,
    });
    expect(sourceRow(db)?.publishedAt).toBe("2026-11-03T10:19:36Z");

    await store.applyPage({ rows: { sources: [pulledSource({})], artifacts: [], cards: [] }, position: 2, more: false });
    expect(sourceRow(db)?.publishedAt).toBeNull();
  });

  it("stores a pulled source's confirm_url, and a missing one as null", async () => {
    const { db, store } = makeDbStore();
    await store.applyPage({
      rows: { sources: [pulledSource({ confirm_url: "https://example.com/confirm-signup" })], artifacts: [], cards: [] },
      position: 1,
      more: false,
    });
    expect(sourceRow(db)?.confirmUrl).toBe("https://example.com/confirm-signup");

    await store.applyPage({ rows: { sources: [pulledSource({})], artifacts: [], cards: [] }, position: 2, more: false });
    expect(sourceRow(db)?.confirmUrl).toBeNull();
  });

  it("stores a pulled note's markdown, dates and refresh state, and missing ones as defaults", async () => {
    const { db, store } = makeDbStore();
    await store.applyPage({
      rows: {
        sources: [
          pulledSource({
            note_markdown: "# Title\n- one",
            note_edited_at: "2024-02-13T12:00:00Z",
            refreshed_at: "2024-03-01T08:00:00Z",
            refreshed_from_queue: true,
            refresh_skipped_at: "2024-03-02T08:00:00Z",
          }),
        ],
        artifacts: [],
        cards: [],
      },
      position: 1,
      more: false,
    });
    expect(sourceRow(db)).toMatchObject({
      noteMarkdown: "# Title\n- one",
      noteEditedAt: "2024-02-13T12:00:00Z",
      refreshedAt: "2024-03-01T08:00:00Z",
      refreshedFromQueue: 1,
      refreshSkippedAt: "2024-03-02T08:00:00Z",
    });

    await store.applyPage({ rows: { sources: [pulledSource({})], artifacts: [], cards: [] }, position: 2, more: false });
    expect(sourceRow(db)).toMatchObject({
      noteMarkdown: null,
      noteEditedAt: null,
      refreshedAt: null,
      refreshedFromQueue: 0,
      refreshSkippedAt: null,
    });
  });

  it("stores a pulled source's sender_address and sender_pending, and missing ones as null and false", async () => {
    const { db, store } = makeDbStore();
    await store.applyPage({
      rows: {
        sources: [pulledSource({ sender_address: "crew@example.com", sender_pending: true })],
        artifacts: [],
        cards: [],
      },
      position: 1,
      more: false,
    });
    expect(sourceRow(db)).toMatchObject({ senderAddress: "crew@example.com", senderPending: true });

    await store.applyPage({ rows: { sources: [pulledSource({})], artifacts: [], cards: [] }, position: 2, more: false });
    expect(sourceRow(db)).toMatchObject({ senderAddress: null, senderPending: false });
  });

  it("stores a pulled book's author, and a missing one as null", async () => {
    const { db, store } = makeDbStore();
    await store.applyPage({
      rows: { sources: [pulledSource({ kind: "book", author: "Ben Macintyre" })], artifacts: [], cards: [] },
      position: 1,
      more: false,
    });
    expect(sourceRow(db)).toMatchObject({ kind: "book", author: "Ben Macintyre" });

    await store.applyPage({ rows: { sources: [pulledSource({})], artifacts: [], cards: [] }, position: 2, more: false });
    expect(sourceRow(db)?.author).toBeNull();
  });

  it("stores pulled newsletter senders, updates one on a later pull, and reads a missing table as none", async () => {
    const { db, store } = makeDbStore();
    const sender = (overrides: Record<string, unknown>) => ({
      id: "n1", label: "Example Weekly", status: "blocked", created_at: "2026-11-01T00:00:00Z",
      updated_at: "2026-11-01T00:00:00Z", change_seq: 4, ...overrides,
    });
    const rows = () => db.select().from(schema.newsletterSenders).all();

    await store.applyPage({
      rows: { sources: [], artifacts: [], cards: [], newsletter_senders: [sender({})] },
      position: 1,
      more: false,
    });
    expect(rows()).toEqual([
      { id: "n1", label: "Example Weekly", status: "blocked", createdAt: "2026-11-01T00:00:00Z", updatedAt: "2026-11-01T00:00:00Z", changeSeq: 4 },
    ]);

    await store.applyPage({
      rows: { sources: [], artifacts: [], cards: [], newsletter_senders: [sender({ status: "allowed", change_seq: 9 })] },
      position: 2,
      more: false,
    });
    expect(rows()).toMatchObject([{ status: "allowed", changeSeq: 9 }]);

    await store.applyPage({ rows: { sources: [], artifacts: [], cards: [] }, position: 3, more: false });
    expect(rows()).toHaveLength(1);
  });

  it("a rejected set_sender_status rewinds the position and marks no source", async () => {
    const { db, store } = makeDbStore();
    db.insert(schema.sources).values({
      id: "s1", url: "newsletter:x", kind: "newsletter", state: "inbox", intent: "queue",
      createdAt: "2026-11-01T00:00:00Z", updatedAt: "2026-11-01T00:00:00Z", processing: "pending",
    }).run();
    db.update(schema.syncState).set({ position: 42 }).where(eq(schema.syncState.id, 1)).run();
    db.insert(schema.outbox).values({
      id: "o1", type: "set_sender_status", payload: JSON.stringify({ source_id: "s1", status: "allowed" }),
      createdAt: "2026-11-01T00:00:00Z", status: "pending",
    }).run();

    await store.rejectAction("o1", "unknown source");

    expect(await store.getPosition()).toBe(0);
    expect(sourceRow(db)?.syncError).toBeNull();
  });

  it("a re-pull of a source with an unsent set_favorite keeps the local star", async () => {
    const { db, store } = makeDbStore();
    await store.applyPage({ rows: { sources: [pulledSource({})], artifacts: [], cards: [] }, position: 1, more: false });
    setFavorite(db, "s1", true);

    await store.applyPage({ rows: { sources: [pulledSource({})], artifacts: [], cards: [] }, position: 2, more: false });

    expect(sourceRow(db)?.favoritedAt).not.toBeNull();
  });

  it("a rejected set_favorite rewinds the position and surfaces syncError on the source", async () => {
    const { db, store } = makeDbStore();
    await store.applyPage({ rows: { sources: [pulledSource({})], artifacts: [], cards: [] }, position: 5, more: false });
    setFavorite(db, "s1", true);
    const entry = db.select().from(schema.outbox).get()!;

    await store.rejectAction(entry.id, "source not found");

    expect(await store.getPosition()).toBe(0);
    expect(sourceRow(db)?.syncError).toBe("source not found");
  });

  // 0008 only adds a column; the test guards against a generated table rebuild that drops or mis-copies rows.
  it("the 0008_favorites migration keeps existing sources, unstarred", () => {
    const sqlite = new Database(":memory:");
    const sqlByKey = migrations.migrations as Record<string, string>;
    const runMigration = (idx: number) => {
      for (const statement of sqlByKey[`m${String(idx).padStart(4, "0")}`].split("--> statement-breakpoint")) {
        if (statement.trim()) sqlite.exec(statement);
      }
    };
    const favoritesIdx = migrations.journal.entries.find((entry) => entry.tag === "0008_favorites")!.idx;
    for (let idx = 0; idx < favoritesIdx; idx++) runMigration(idx);
    sqlite
      .prepare(
        "INSERT INTO sources (id, url, kind, state, intent, created_at, updated_at, domain, cards_off) " +
          "VALUES ('s1', 'https://example.com/a', 'article', 'queued', 'queue', 'x', 'x', 'AI', 1)",
      )
      .run();

    runMigration(favoritesIdx);

    expect(sqlite.prepare("SELECT * FROM sources").all()).toEqual([
      expect.objectContaining({ id: "s1", state: "queued", domain: "AI", cards_off: 1, favorited_at: null }),
    ]);
  });
});

const pulledTopic = (overrides: Partial<PulledTopic>): PulledTopic => ({
  id: "t1",
  domain: "Crypto",
  name: "Bitcoin",
  origin: "starter",
  removed_at: null,
  merged_into_id: null,
  created_at: "2026-11-01T00:00:00Z",
  updated_at: "2026-11-01T00:00:00Z",
  ...overrides,
});

const pulledTopicPrimer = (
  overrides: Partial<PulledTopicPrimer>,
): PulledTopicPrimer => ({
  id: "p1",
  topic_id: "t1",
  version: 1,
  is_current: true,
  content: { markdown: "# Bitcoin" },
  opened_at: null,
  snoozed_until: null,
  created_at: "2026-11-02T00:00:00Z",
  ...overrides,
});

const topicsPage = (
  topics: PulledTopic[],
  topicPrimers: PulledTopicPrimer[] = [],
): PullPage => ({
  rows: {
    sources: [],
    artifacts: [],
    cards: [],
    topics,
    topic_primers: topicPrimers,
  },
  position: 3,
  more: false,
});

const topicById = (db: AppDb, id: string) =>
  db.select().from(schema.topics).where(eq(schema.topics.id, id)).get();

describe("database SyncStore: library rows", () => {
  it("stores pulled topics and topic primers (content as JSON text)", async () => {
    const { db, store } = makeDbStore();

    await store.applyPage(
      topicsPage(
        [pulledTopic({ removed_at: "2026-11-03T00:00:00Z" })],
        [pulledTopicPrimer({})],
      ),
    );

    expect(topicById(db, "t1")).toMatchObject({
      domain: "Crypto",
      name: "Bitcoin",
      origin: "starter",
      removedAt: "2026-11-03T00:00:00Z",
      mergedIntoId: null,
    });
    const primer = db.select().from(schema.topicPrimers).get();
    expect(primer).toMatchObject({
      topicId: "t1",
      version: 1,
      isCurrent: 1,
      openedAt: null,
    });
    expect(JSON.parse(primer!.content)).toEqual({ markdown: "# Bitcoin" });
  });

  it("keeps a topic's local copy while an action on it is unsent", async () => {
    const { db, store } = makeDbStore();
    await store.applyPage(topicsPage([pulledTopic({})]));
    db.update(schema.topics)
      .set({ name: "BTC" })
      .where(eq(schema.topics.id, "t1"))
      .run();
    db.insert(schema.outbox)
      .values({
        id: "o1",
        type: "rename_topic",
        payload: JSON.stringify({ id: "t1", name: "BTC" }),
        createdAt: "x",
        status: "pending",
      })
      .run();

    await store.applyPage(topicsPage([pulledTopic({ name: "Bitcoin" })]));

    expect(topicById(db, "t1")?.name).toBe("BTC");
  });

  it("never clears the phone-only primerRequestedAt on a later pull", async () => {
    const { db, store } = makeDbStore();
    await store.applyPage(topicsPage([pulledTopic({})]));
    db.update(schema.topics)
      .set({ primerRequestedAt: "2026-11-04T00:00:00Z" })
      .where(eq(schema.topics.id, "t1"))
      .run();

    await store.applyPage(topicsPage([pulledTopic({ name: "Bitcoin!" })]));

    expect(topicById(db, "t1")).toMatchObject({
      name: "Bitcoin!",
      primerRequestedAt: "2026-11-04T00:00:00Z",
    });
  });

  it("deletes the optimistic topic when its add_topic is rejected", async () => {
    const { db, store } = makeDbStore();
    db.insert(schema.topics)
      .values({
        id: "t1",
        domain: "AI",
        name: "Evals",
        origin: "user",
        createdAt: "x",
        updatedAt: "x",
      })
      .run();
    db.insert(schema.outbox)
      .values({
        id: "o1",
        type: "add_topic",
        payload: JSON.stringify({ id: "t1", domain: "AI", name: "Evals" }),
        createdAt: "x",
        status: "pending",
      })
      .run();

    await store.rejectAction("o1", "a topic with this name exists");

    expect(topicById(db, "t1")).toBeUndefined();
    expect(db.select().from(schema.outbox).get()).toMatchObject({
      status: "rejected",
      error: "a topic with this name exists",
    });
  });

  const queueRejectable = (db: AppDb, type: string, payload: object) => {
    db.insert(schema.outbox)
      .values({
        id: "o1",
        type,
        payload: JSON.stringify(payload),
        createdAt: "x",
        status: "pending",
      })
      .run();
    db.update(schema.syncState).set({ position: 7 }).where(eq(schema.syncState.id, 1)).run();
  };
  const position = (db: AppDb) =>
    db.select().from(schema.syncState).get()?.position;

  it("deletes every optimistic topic when its choose_topics is rejected", async () => {
    const { db, store } = makeDbStore();
    for (const id of ["t1", "t2"]) {
      db.insert(schema.topics)
        .values({
          id,
          domain: "AI",
          name: id,
          origin: "starter",
          createdAt: "x",
          updatedAt: "x",
        })
        .run();
    }
    queueRejectable(db, "choose_topics", {
      topics: [{ id: "t1" }, { id: "t2" }],
    });

    await store.rejectAction("o1", "bad topics");

    expect(db.select().from(schema.topics).all()).toEqual([]);
  });

  it("rewinds the position to 0 when a rename_topic is rejected", async () => {
    const { db, store } = makeDbStore();
    queueRejectable(db, "rename_topic", { id: "t1", name: "x" });

    await store.rejectAction("o1", "name taken");

    expect(position(db)).toBe(0);
  });

  it("rewinds the position to 0 when a topic_primer snooze is rejected", async () => {
    const { db, store } = makeDbStore();
    queueRejectable(db, "snooze", {
      target: "topic_primer",
      id: "t1",
      until: null,
    });

    await store.rejectAction("o1", "nope");

    expect(position(db)).toBe(0);
  });

  it("leaves the position alone when a source action is rejected", async () => {
    const { db, store } = makeDbStore();
    queueRejectable(db, "snooze", { target: "source", id: "s1", until: null });

    await store.rejectAction("o1", "nope");

    expect(position(db)).toBe(7);
  });

  it("stores a pulled source's filing, artwork and reading fields", async () => {
    const { db, store } = makeDbStore();
    const fields = {
      domain: "Crypto",
      topic_id: "t1",
      image_url: "https://example.com/art.jpg",
      queue_position: -2.5,
      read_at: "2026-11-03T00:00:00Z",
      snoozed_until: "2026-11-05T14:00:00Z",
      primer_opened_at: "2026-11-03T01:00:00Z",
      newsletter_kind: "digest",
    };

    await store.applyPage({
      rows: {
        sources: [pulledSource(fields)],
        artifacts: [],
        cards: [],
        topics: [],
        topic_primers: [],
      },
      position: 1,
      more: false,
    });

    expect(db.select().from(schema.sources).get()).toMatchObject({
      domain: "Crypto",
      topicId: "t1",
      imageUrl: "https://example.com/art.jpg",
      queuePosition: -2.5,
      readAt: "2026-11-03T00:00:00Z",
      snoozedUntil: "2026-11-05T14:00:00Z",
      primerOpenedAt: "2026-11-03T01:00:00Z",
      newsletterKind: "digest",
    });
  });
});

describe("database SyncStore: M4 migration and rejections", () => {
  it("applies a page from a pre-M4 server (no topics keys) and saves the position", async () => {
    const { db, store } = makeDbStore();
    const legacyRows = { sources: [pulledSource({})], artifacts: [], cards: [] };

    await store.applyPage({ rows: legacyRows, position: 9, more: false });

    expect(db.select().from(schema.sources).all()).toHaveLength(1);
    expect(await store.getPosition()).toBe(9);
  });

  // Each migration that adds server columns ends by resetting the saved position, so phones re-pull every row.
  it.each(["0005_queued_primers", "0006_briefs", "0007_review", "0008_favorites", "0009_collections", "0010_takes", "0011_search_ask", "0012_published_at", "0013_chat_edits", "0014_confirm_url", "0015_newsletter_senders", "0016_notes", "0017_chat_cards"])("the %s migration ends by resetting a saved position to 0", (tag) => {
    const { db } = makeDbStore();
    db.update(schema.syncState).set({ position: 42 }).where(eq(schema.syncState.id, 1)).run();
    const entry = migrations.journal.entries.find((candidate) => candidate.tag === tag)!;
    const sql = (migrations.migrations as Record<string, string>)[`m${String(entry.idx).padStart(4, "0")}`];

    // Only the reset is replayed: the column changes before it have already run on this database.
    db.run(sqlTag(sql.split("--> statement-breakpoint").at(-1)!));

    expect(db.select().from(schema.syncState).get()?.position).toBe(0);
  });

  it("stores a pulled card's and card version's detail, and reads an older server's missing one as empty", async () => {
    const { db, store } = makeDbStore();
    await store.applyPage({
      rows: {
        sources: [],
        artifacts: [],
        cards: [pulledCard({ detail: "Why.\nHow." })],
        card_versions: [
          { id: "cv1", card_id: "c1", version: 1, question: "Q?", answer: "A.", detail: "Why.", origin: "archie", instruction: null, created_at: "x", change_seq: 3 },
          { id: "cv2", card_id: "c1", version: 2, question: "Q?", answer: "B.", origin: "care", instruction: null, created_at: "y", change_seq: 4 },
        ],
      },
      position: 4,
      more: false,
    });
    expect(db.select().from(schema.cards).get()?.detail).toBe("Why.\nHow.");
    expect(db.select().from(schema.cardVersions).all().map((row) => row.detail)).toEqual(["Why.", ""]);

    await store.applyPage({ rows: { sources: [], artifacts: [], cards: [pulledCard({})] }, position: 5, more: false });
    expect(db.select().from(schema.cards).get()?.detail).toBe("");
  });

  it("stores pulled card versions, edit proposals and version origins", async () => {
    const { db, store } = makeDbStore();
    await store.applyPage({
      rows: {
        sources: [],
        artifacts: [pulledArtifact({ origin: "chat_edit", instruction: "Drop the jargon" })],
        cards: [pulledCard({ version: 2 })],
        card_versions: [
          { id: "cv1", card_id: "c1", version: 1, question: "Q?", answer: "A.", origin: "archie", instruction: null, created_at: "x", change_seq: 3 },
        ],
        edit_proposals: [
          {
            id: "p1",
            conversation_id: "k1",
            message_id: "m1",
            target_kind: "card",
            target_id: "c1",
            title: "Q?",
            description: "Say B",
            base_version: 1,
            before: { question: "Q?", answer: "A." },
            after: { question: "Q?", answer: "B." },
            status: "applied",
            applied_version: 2,
            created_at: "x",
            updated_at: "y",
            change_seq: 4,
          },
        ],
      },
      position: 4,
      more: false,
    });

    expect(db.select().from(schema.artifacts).get()).toEqual(
      expect.objectContaining({ origin: "chat_edit", instruction: "Drop the jargon" }),
    );
    expect(db.select().from(schema.cards).get()?.version).toBe(2);
    expect(db.select().from(schema.cardVersions).all()).toEqual([expect.objectContaining({ cardId: "c1", version: 1 })]);
    expect(db.select().from(schema.editProposals).get()).toEqual(
      expect.objectContaining({ status: "applied", appliedVersion: 2, after: JSON.stringify({ question: "Q?", answer: "B." }) }),
    );
  });

  it("stores pulled card sets, and a chat item's chat, with a missing one as null", async () => {
    const { db, store } = makeDbStore();
    const cardSet = {
      id: "cs1",
      conversation_id: "k1",
      message_id: "m1",
      title: "JWT vs session tokens",
      cheat_sheet: "## The difference",
      cards: [{ kind: "concept", question: "Q?", answer: "A.", detail: [] }],
      status: "proposed",
      saved_source_id: null,
      kept: null,
      created_at: "x",
      updated_at: "x",
      change_seq: 5,
    };
    await store.applyPage({
      rows: {
        sources: [pulledSource({ kind: "chat", chat_conversation_id: "k1" })],
        artifacts: [],
        cards: [],
        card_set_proposals: [cardSet],
      },
      position: 5,
      more: false,
    });
    expect(sourceRow(db)?.chatConversationId).toBe("k1");
    expect(db.select().from(schema.cardSetProposals).get()).toEqual(
      expect.objectContaining({ status: "proposed", kept: null, cards: JSON.stringify(cardSet.cards) }),
    );

    // A later pull of the same set (saved now) updates it in place.
    await store.applyPage({
      rows: {
        sources: [pulledSource({})],
        artifacts: [],
        cards: [],
        card_set_proposals: [{ ...cardSet, status: "saved", saved_source_id: "s1", kept: [0], change_seq: 6 }],
      },
      position: 6,
      more: false,
    });
    expect(sourceRow(db)?.chatConversationId).toBeNull();
    expect(db.select().from(schema.cardSetProposals).all()).toEqual([
      expect.objectContaining({ id: "cs1", status: "saved", savedSourceId: "s1", kept: "[0]" }),
    ]);
  });

  it("a rejected go_deeper surfaces syncError, rewinds the position, and the next pull restores the server copy", async () => {
    const { db, store } = makeDbStore();
    await store.applyPage({
      rows: { sources: [pulledSource({ state: "inbox", processing: "ready" })], artifacts: [], cards: [] },
      position: 5,
      more: false,
    });
    goDeeper(db, "s1");
    const entry = db.select().from(schema.outbox).get()!;

    await store.rejectAction(entry.id, "not ready");

    expect(await store.getPosition()).toBe(0);
    expect(sourceRow(db)).toMatchObject({ state: "consumed", processing: "processing", syncError: "not ready" });

    await store.applyPage({
      rows: { sources: [pulledSource({ state: "inbox", processing: "ready" })], artifacts: [], cards: [] },
      position: 6,
      more: false,
    });

    // The pull restores state/processing; syncError is deliberately outside the upsert set, so it stays.
    expect(sourceRow(db)).toMatchObject({ state: "inbox", processing: "ready", syncError: "not ready" });
  });

  it.each(["queue_primer", "request_primer", "return_to_inbox"])(
    "a rejected %s rewinds the position so the next pull restores the server copy",
    async (type) => {
      const { db, store } = makeDbStore();
      await store.applyPage({
        rows: { sources: [pulledSource({ state: "queued" })], artifacts: [], cards: [] },
        position: 5,
        more: false,
      });
      const actions = {
        queue_primer: () => queuePrimer(db, "s1", true),
        request_primer: () => requestPrimer(db, "s1"),
        return_to_inbox: () => returnToInbox(db, "s1"),
      };
      actions[type as keyof typeof actions]();
      const entry = db.select().from(schema.outbox).get()!;

      await store.rejectAction(entry.id, "nope");

      expect(await store.getPosition()).toBe(0);
      expect(sourceRow(db)?.syncError).toBe("nope");
    },
  );

  it("a rejected source_primer snooze rewinds the position and surfaces syncError on the source", async () => {
    const { db, store } = makeDbStore();
    await store.applyPage({
      rows: { sources: [pulledSource({ state: "consumed" })], artifacts: [], cards: [] },
      position: 5,
      more: false,
    });
    snooze(db, "source_primer", "s1", new Date("2099-01-01T00:00:00Z"));
    const entry = db.select().from(schema.outbox).get()!;

    await store.rejectAction(entry.id, "nope");

    expect(await store.getPosition()).toBe(0);
    expect(sourceRow(db)?.syncError).toBe("nope");
  });
});

describe("database SyncStore: cards and review actions", () => {
  const reviewedFields = {
    fsrsState: "review" as const,
    stability: 4.5,
    difficulty: 5.2,
    dueAt: "2026-11-10T00:00:00.000Z",
    lastReviewAt: "2026-11-05T00:00:00.000Z",
    reps: 3,
    lapses: 1,
  };
  const newFields = { ...reviewedFields, fsrsState: "new" as const, stability: null, difficulty: null, dueAt: null, lastReviewAt: null, reps: 0, lapses: 0 };
  const cardPage = (cards: PulledCard[], position = 5): PullPage => ({
    rows: { sources: [pulledSource({})], artifacts: [], cards },
    position,
    more: false,
  });

  it("stores a pulled card's FSRS state and origins, with no source", async () => {
    const { db, store } = makeDbStore();

    await store.applyPage(
      cardPage([
        pulledCard({
          id: "quiz",
          source_id: null,
          brief_id: "b1",
          kind: "quiz",
          fsrs_state: "review",
          stability: 4.5,
          difficulty: 5.2,
          due_at: "2026-11-10T00:00:00Z",
          last_review_at: "2026-11-05T00:00:00Z",
          reps: 3,
          lapses: 1,
          expires_at: "2026-11-12T00:00:00Z",
        }),
        pulledCard({ id: "legacy" }),
      ]),
    );

    const card = (id: string) => db.select().from(schema.cards).where(eq(schema.cards.id, id)).get();
    expect(card("quiz")).toMatchObject({
      sourceId: null,
      topicPrimerId: null,
      briefId: "b1",
      fsrsState: "review",
      stability: 4.5,
      difficulty: 5.2,
      dueAt: "2026-11-10T00:00:00Z",
      lastReviewAt: "2026-11-05T00:00:00Z",
      reps: 3,
      lapses: 1,
      expiresAt: "2026-11-12T00:00:00Z",
    });
    // A server older than M6 sends no FSRS fields: the card is new.
    expect(card("legacy")).toMatchObject({ sourceId: "s1", briefId: null, fsrsState: "new", stability: null, reps: 0, lapses: 0 });
  });

  it("stores a pulled card's available_at, and a missing one as null", async () => {
    const { db, store } = makeDbStore();

    await store.applyPage(
      cardPage([pulledCard({ id: "later", available_at: "2026-11-24T00:00:00Z" }), pulledCard({ id: "now" })]),
    );

    const card = (id: string) => db.select().from(schema.cards).where(eq(schema.cards.id, id)).get();
    expect(card("later")?.availableAt).toBe("2026-11-24T00:00:00Z");
    expect(card("now")?.availableAt).toBeNull();
  });

  it("keeps a card's local schedule while its review_card is unsent", async () => {
    const { db, store } = makeDbStore();
    await store.applyPage(cardPage([pulledCard({})]));
    reviewCard(db, {
      cardId: "c1",
      grade: "got_it",
      gradedBy: "model",
      answer: "A.",
      missing: "",
      wasDue: true,
      reviewedAt: new Date("2026-11-05T00:00:00Z"),
      stateBefore: newFields,
      stateAfter: reviewedFields,
    });

    await store.applyPage(cardPage([pulledCard({ answer: "Server answer" })], 6));

    expect(db.select().from(schema.cards).get()).toMatchObject({ ...reviewedFields, answer: "A." });
    expect(await store.getPosition()).toBe(6);
  });

  it("stores a pulled source's cards_off as 1", async () => {
    const { db, store } = makeDbStore();

    await store.applyPage({ rows: { sources: [pulledSource({ cards_off: true })], artifacts: [], cards: [] }, position: 1, more: false });

    expect(sourceRow(db)?.cardsOff).toBe(1);
  });

  it.each(["review_card", "drop_card"])(
    "a rejected %s rewinds the position and leaves the source alone",
    async (type) => {
      const { db, store } = makeDbStore();
      await store.applyPage(cardPage([pulledCard({})]));
      const actions = {
        review_card: () =>
          reviewCard(db, {
            cardId: "c1",
            grade: "missed",
            gradedBy: "self",
            answer: null,
            missing: null,
            wasDue: true,
            reviewedAt: new Date("2026-11-05T00:00:00Z"),
            stateBefore: newFields,
            stateAfter: reviewedFields,
          }),
        drop_card: () => dropCard(db, "c1"),
      };
      actions[type as keyof typeof actions]();
      const entry = db.select().from(schema.outbox).get()!;

      await store.rejectAction(entry.id, "nope");

      expect(await store.getPosition()).toBe(0);
      expect(sourceRow(db)?.syncError).toBeNull();
    },
  );

  it("a rejected set_cards_off rewinds the position and surfaces syncError on the source", async () => {
    const { db, store } = makeDbStore();
    await store.applyPage(cardPage([pulledCard({})]));
    setCardsOff(db, "s1", true);
    const entry = db.select().from(schema.outbox).get()!;

    await store.rejectAction(entry.id, "nope");

    expect(await store.getPosition()).toBe(0);
    expect(sourceRow(db)?.syncError).toBe("nope");
  });

  // 0007 rebuilds the cards table (source_id became nullable) with a hand-trimmed copy of the old columns.
  it("the 0007_review migration keeps existing cards, as new cards", () => {
    const sqlite = new Database(":memory:");
    const sqlByKey = migrations.migrations as Record<string, string>;
    const runMigration = (idx: number) => {
      for (const statement of sqlByKey[`m${String(idx).padStart(4, "0")}`].split("--> statement-breakpoint")) {
        if (statement.trim()) sqlite.exec(statement);
      }
    };
    const reviewIdx = migrations.journal.entries.find((entry) => entry.tag === "0007_review")!.idx;
    for (let idx = 0; idx < reviewIdx; idx++) runMigration(idx);
    sqlite
      .prepare(
        "INSERT INTO cards (id, source_id, kind, question, answer, created_at) VALUES ('c1', 's1', 'concept', 'Q?', 'A.', 'x')",
      )
      .run();

    runMigration(reviewIdx);

    expect(sqlite.prepare("SELECT * FROM cards").all()).toEqual([
      expect.objectContaining({ id: "c1", source_id: "s1", question: "Q?", fsrs_state: "new", reps: 0, lapses: 0, due_at: null }),
    ]);
  });
});

const sourceRow = (db: AppDb) => db.select().from(schema.sources).where(eq(schema.sources.id, "s1")).get();
const sqlTag = (text: string) => sql.raw(text);

describe("createSyncScheduler", () => {
  it("never overlaps runs and coalesces triggers that arrive mid-run into one rerun", async () => {
    let active = 0;
    let maxActive = 0;
    let runs = 0;
    let release: () => void = () => undefined;
    const trigger = createSyncScheduler(async () => {
      runs += 1;
      active += 1;
      maxActive = Math.max(maxActive, active);
      await new Promise<void>((resolve) => {
        release = resolve;
      });
      active -= 1;
    });

    const first = trigger();
    await trigger();
    await trigger();
    await trigger();
    release();
    await new Promise((resolve) => setImmediate(resolve));
    release();
    await first;

    expect(runs).toBe(2);
    expect(maxActive).toBe(1);
  });

  it("runs the coalesced rerun even when the run it landed in throws, then rethrows the first error", async () => {
    let runs = 0;
    let release: () => void = () => undefined;
    let trigger: () => Promise<void> = async () => undefined;
    trigger = createSyncScheduler(async () => {
      runs += 1;
      if (runs > 1) throw new Error("second");
      await new Promise<void>((resolve) => {
        release = resolve;
      });
      throw new Error("first");
    });

    const first = trigger();
    const settled = first.catch((error: Error) => error);
    await trigger();
    release();

    expect(await settled).toEqual(new Error("first"));
    expect(runs).toBe(2);
  });
});

describe("sign-out during a sync run", () => {
  function wipe(db: AppDb): void {
    db.delete(schema.sources).run();
    db.delete(schema.outbox).run();
    db.update(schema.syncState).set({ position: 0, lastPushFailed: 0 }).run();
  }

  it("drops the in-flight run's pulled rows and position once the session epoch moved on", async () => {
    const { db } = makeDbStore();
    const store = createDbSyncStore(db, getSessionEpoch());
    const transport: SyncTransport = {
      async push() {
        return [];
      },
      async pull() {
        // The user signs out (epoch bump, then wipe) while this response is on the wire.
        bumpSessionEpoch();
        wipe(db);
        return {
          rows: {
            sources: [pulledSource({ id: "old-account" })],
            artifacts: [],
            cards: [],
            topics: [],
            topic_primers: [],
          },
          position: 7,
          more: false,
        };
      },
    };

    expect(await runSync(store, transport)).toBe("synced");

    expect(db.select().from(schema.sources).all()).toEqual([]);
    expect(await store.getPosition()).toBe(0);
  });

  it("drops a late push settlement too: no outbox removal, rejection or failure flag", async () => {
    const { db } = makeDbStore();
    db.insert(schema.sources)
      .values({ ...pulledSource({}), createdAt: "x", updatedAt: "x" })
      .run();
    db.insert(schema.outbox)
      .values({
        id: "o1",
        type: "add_source",
        payload: JSON.stringify({ id: "s1" }),
        createdAt: "x",
        status: "pending",
      })
      .run();
    const store = createDbSyncStore(db, getSessionEpoch());

    bumpSessionEpoch();
    await store.rejectAction("o1", "late");
    await store.removeActions(["o1"]);
    await store.setLastPushFailed(true);

    expect(db.select().from(schema.outbox).get()).toMatchObject({
      id: "o1",
      status: "pending",
      error: null,
    });
    expect(db.select().from(schema.sources).get()?.syncError).toBeNull();
    expect(db.select().from(schema.syncState).get()?.lastPushFailed).toBe(0);
  });
});

const pulledCollection = (overrides: Partial<PulledCollection>): PulledCollection => ({
  id: "c1",
  name: "Bears hype",
  position: 0,
  created_at: "2026-11-05T00:00:00Z",
  updated_at: "2026-11-05T00:00:00Z",
  deleted_at: null,
  ...overrides,
});

const pulledItem = (overrides: Partial<PulledCollectionItem>): PulledCollectionItem => ({
  id: "i1",
  collection_id: "c1",
  url: "https://x.com/BearsFilmRoom/status/1",
  kind: "x",
  title: null,
  author: null,
  image_url: null,
  duration_seconds: null,
  note: null,
  metadata_status: "ready",
  created_at: "2026-11-05T00:00:00Z",
  updated_at: "2026-11-05T00:00:00Z",
  deleted_at: null,
  ...overrides,
});

describe("database SyncStore: collections", () => {
  it("stores pulled collections and posts, and a page without them is fine", async () => {
    const { db, store } = makeDbStore();
    await store.applyPage({
      rows: {
        sources: [],
        artifacts: [],
        cards: [],
        collections: [pulledCollection({ name: "Bears hype" })],
        collection_items: [pulledItem({ title: "Walk-off pick six", duration_seconds: 65 })],
      },
      position: 3,
      more: false,
    });
    await store.applyPage({ rows: { sources: [], artifacts: [], cards: [] }, position: 4, more: false });

    expect(db.select().from(schema.collections).get()).toMatchObject({ id: "c1", name: "Bears hype", position: 0 });
    expect(db.select().from(schema.collectionItems).get()).toMatchObject({
      id: "i1",
      collectionId: "c1",
      kind: "x",
      title: "Walk-off pick six",
      durationSeconds: 65,
      metadataStatus: "ready",
    });
    expect(await store.getPosition()).toBe(4);
  });

  it("a re-pull updates a collection and its post over the local copy", async () => {
    const { db, store } = makeDbStore();
    const rows = { sources: [], artifacts: [], cards: [] };
    await store.applyPage({
      rows: { ...rows, collections: [pulledCollection({})], collection_items: [pulledItem({})] },
      position: 1,
      more: false,
    });

    await store.applyPage({
      rows: {
        ...rows,
        collections: [pulledCollection({ name: "Bears film room" })],
        collection_items: [pulledItem({ note: "the scramble", deleted_at: "2026-11-06T00:00:00Z" })],
      },
      position: 2,
      more: false,
    });

    expect(db.select().from(schema.collections).get()?.name).toBe("Bears film room");
    expect(db.select().from(schema.collectionItems).get()).toMatchObject({
      note: "the scramble",
      deletedAt: "2026-11-06T00:00:00Z",
    });
  });

  it("a re-pull of a collection or post with an unsent edit keeps the local copy", async () => {
    const { db, store } = makeDbStore();
    const page = {
      rows: { sources: [], artifacts: [], cards: [], collections: [pulledCollection({})], collection_items: [pulledItem({})] },
      position: 1,
      more: false,
    };
    await store.applyPage(page);
    renameCollection(db, "c1", "Mine");
    editCollectionItemNote(db, "i1", "mine");

    await store.applyPage({ ...page, position: 2 });

    expect(db.select().from(schema.collections).get()?.name).toBe("Mine");
    expect(db.select().from(schema.collectionItems).get()?.note).toBe("mine");
  });

  it("a rejected create_collection deletes the optimistic collection and its posts", async () => {
    const { db, store } = makeDbStore();
    const collectionId = createCollection(db, "Bears hype");
    addCollectionItem(db, { collectionId, url: "https://example.com/a" });
    const create = db.select().from(schema.outbox).all().find((entry) => entry.type === "create_collection")!;

    await store.rejectAction(create.id, "id already exists");

    expect(db.select().from(schema.collections).all()).toEqual([]);
    expect(db.select().from(schema.collectionItems).all()).toEqual([]);
  });

  it("a rejected add_collection_item deletes the optimistic post and touches no source", async () => {
    const { db, store } = makeDbStore();
    await store.applyPage({
      rows: { sources: [pulledSource({})], artifacts: [], cards: [], collections: [pulledCollection({})] },
      position: 5,
      more: false,
    });
    addCollectionItem(db, { collectionId: "c1", url: "https://example.com/a" });
    const add = db.select().from(schema.outbox).get()!;

    await store.rejectAction(add.id, "collection not found");

    expect(db.select().from(schema.collectionItems).all()).toEqual([]);
    expect(db.select().from(schema.collections).all()).toHaveLength(1);
    expect(sourceRow(db)?.syncError).toBeNull();
    expect(await store.getPosition()).toBe(5);
  });

  it.each(["update_collection", "update_collection_item"])(
    "a rejected %s rewinds the position and touches no source",
    async (type) => {
      const { db, store } = makeDbStore();
      await store.applyPage({
        rows: {
          sources: [pulledSource({})],
          artifacts: [],
          cards: [],
          collections: [pulledCollection({})],
          collection_items: [pulledItem({})],
        },
        position: 5,
        more: false,
      });
      if (type === "update_collection") renameCollection(db, "c1", "New name");
      else removeCollectionItem(db, "i1");
      const entry = db.select().from(schema.outbox).get()!;

      await store.rejectAction(entry.id, "collection not found");

      expect(entry.type).toBe(type);
      expect(await store.getPosition()).toBe(0);
      expect(sourceRow(db)?.syncError).toBeNull();
    },
  );
});

const pulledTake = (overrides: Partial<PulledTake>): PulledTake => ({
  id: "k1",
  kind: "opinion",
  title: "Remote work is worse for juniors",
  current_version: 1,
  created_at: "2026-11-05T00:00:00Z",
  updated_at: "2026-11-05T00:00:00Z",
  deleted_at: null,
  ...overrides,
});

const pulledVersion = (overrides: Partial<PulledTakeVersion>): PulledTakeVersion => ({
  id: "v1",
  take_id: "k1",
  version: 1,
  body: "Juniors learn by overhearing.",
  raw_body: "Juniors learn by overhearing.",
  cleaned: false,
  clean_failed: false,
  created_at: "2026-11-05T00:00:00Z",
  ...overrides,
});

describe("database SyncStore: takes", () => {
  const takePage = (overrides: Partial<PullPage["rows"]> = {}, position = 5): PullPage => ({
    rows: {
      sources: [pulledSource({})],
      artifacts: [],
      cards: [],
      takes: [pulledTake({})],
      take_versions: [pulledVersion({})],
      ...overrides,
    },
    position,
    more: false,
  });
  const takeRow = (db: AppDb) => db.select().from(schema.takes).where(eq(schema.takes.id, "k1")).get();
  const versionIds = (db: AppDb) =>
    db.select().from(schema.takeVersions).all().map((version) => version.id).sort();
  const outboxEntry = (db: AppDb, type: string) =>
    db.select().from(schema.outbox).all().find((entry) => entry.type === type)!;

  it("stores pulled takes, versions and take cards; a page without them is fine", async () => {
    const { db, store } = makeDbStore();

    await store.applyPage(
      takePage({
        take_versions: [pulledVersion({ cleaned: true, clean_failed: true })],
        cards: [pulledCard({ id: "c1", source_id: null, kind: "take", take_id: "k1", take_version_id: "v1" })],
      }),
    );
    await store.applyPage({ rows: { sources: [], artifacts: [], cards: [pulledCard({ id: "c2" })] }, position: 6, more: false });

    expect(takeRow(db)).toMatchObject({ kind: "opinion", title: "Remote work is worse for juniors", currentVersion: 1 });
    expect(db.select().from(schema.takeVersions).get()).toMatchObject({
      id: "v1",
      takeId: "k1",
      body: "Juniors learn by overhearing.",
      cleaned: 1,
      cleanFailed: 1,
    });
    const card = (id: string) => db.select().from(schema.cards).where(eq(schema.cards.id, id)).get();
    expect(card("c1")).toMatchObject({ sourceId: null, takeId: "k1", takeVersionId: "v1" });
    expect(card("c2")).toMatchObject({ sourceId: "s1", takeId: null, takeVersionId: null });
    expect(await store.getPosition()).toBe(6);
  });

  it("a re-pull of a take or version with an unsent edit keeps the local copy", async () => {
    const { db, store } = makeDbStore();
    await store.applyPage(takePage({ take_versions: [pulledVersion({ cleaned: true, clean_failed: true })] }));
    changeTakeKind(db, "k1", "talking_point");
    retryTakeCleanup(db, "k1", "v1");

    await store.applyPage(takePage({ take_versions: [pulledVersion({ cleaned: true, clean_failed: true })] }, 6));

    expect(takeRow(db)?.kind).toBe("talking_point");
    expect(db.select().from(schema.takeVersions).get()).toMatchObject({ body: null, cleanFailed: 0 });
  });

  it("a re-pull keeps an unsent optimistic version", async () => {
    const { db, store } = makeDbStore();
    const id = saveTake(db, { id: null, kind: "opinion", title: "Mine", body: "Mine.", clean: false });
    const versionId = JSON.parse(outboxEntry(db, "save_take").payload).version_id;

    await store.applyPage(
      takePage({ takes: [], take_versions: [pulledVersion({ id: versionId, take_id: id, body: "Older." })] }),
    );

    expect(db.select().from(schema.takeVersions).get()?.body).toBe("Mine.");
  });

  it("a rejected save_take of a new take deletes it and its version and rewinds", async () => {
    const { db, store } = makeDbStore();
    await store.applyPage(takePage({ takes: [], take_versions: [] }));
    const id = saveTake(db, { id: null, kind: "opinion", title: "Mine", body: "Mine.", clean: false });

    await store.rejectAction(outboxEntry(db, "save_take").id, "take is empty");

    expect(db.select().from(schema.takes).where(eq(schema.takes.id, id)).get()).toBeUndefined();
    expect(db.select().from(schema.takeVersions).all()).toEqual([]);
    expect(await store.getPosition()).toBe(0);
    expect(sourceRow(db)?.syncError).toBeNull();
  });

  it("a rejected save_take on a pulled take deletes only the new version and points the take back", async () => {
    const { db, store } = makeDbStore();
    await store.applyPage(takePage());
    saveTake(db, { id: "k1", kind: "opinion", title: "Remote work is worse for juniors", body: "Changed.", clean: false });
    expect(takeRow(db)?.currentVersion).toBe(2);

    await store.rejectAction(outboxEntry(db, "save_take").id, "take is longer than 20000 characters");

    expect(versionIds(db)).toEqual(["v1"]);
    expect(takeRow(db)?.currentVersion).toBe(1);
    expect(await store.getPosition()).toBe(0);
    expect(sourceRow(db)?.syncError).toBeNull();
  });

  it("a rejected restore_take_version deletes the optimistic copy", async () => {
    const { db, store } = makeDbStore();
    await store.applyPage(
      takePage({
        takes: [pulledTake({ current_version: 2 })],
        take_versions: [pulledVersion({}), pulledVersion({ id: "v2", version: 2, body: "Second." })],
      }),
    );
    restoreTakeVersion(db, "k1", 1);
    expect(takeRow(db)?.currentVersion).toBe(3);

    await store.rejectAction(outboxEntry(db, "restore_take_version").id, "take version not found");

    expect(versionIds(db)).toEqual(["v1", "v2"]);
    expect(takeRow(db)?.currentVersion).toBe(2);
    expect(await store.getPosition()).toBe(0);
    expect(sourceRow(db)?.syncError).toBeNull();
  });

  it.each(["update_take", "retry_take_cleanup"])("a rejected %s rewinds and touches no source", async (type) => {
    const { db, store } = makeDbStore();
    await store.applyPage(takePage());
    if (type === "update_take") changeTakeKind(db, "k1", "talking_point");
    else retryTakeCleanup(db, "k1", "v1");
    const entry = db.select().from(schema.outbox).get()!;

    await store.rejectAction(entry.id, "take not found");

    expect(entry.type).toBe(type);
    expect(await store.getPosition()).toBe(0);
    expect(sourceRow(db)?.syncError).toBeNull();
    expect(takeRow(db)).toBeDefined();
    expect(versionIds(db)).toEqual(["v1"]);
  });

  // 0010 only adds tables and columns; the test guards against a generated cards rebuild that drops a schedule.
  it("the 0010_takes migration keeps an existing card and its schedule", () => {
    const sqlite = new Database(":memory:");
    const sqlByKey = migrations.migrations as Record<string, string>;
    const runMigration = (idx: number) => {
      for (const statement of sqlByKey[`m${String(idx).padStart(4, "0")}`].split("--> statement-breakpoint")) {
        if (statement.trim()) sqlite.exec(statement);
      }
    };
    const takesIdx = migrations.journal.entries.find((entry) => entry.tag === "0010_takes")!.idx;
    for (let idx = 0; idx < takesIdx; idx++) runMigration(idx);
    sqlite
      .prepare(
        "INSERT INTO cards (id, source_id, kind, question, answer, created_at, fsrs_state, stability, due_at, reps) " +
          "VALUES ('c1', 's1', 'concept', 'Q?', 'A.', 'x', 'review', 3.5, '2026-11-09T00:00:00Z', 2)",
      )
      .run();

    runMigration(takesIdx);

    expect(sqlite.prepare("SELECT * FROM cards").all()).toEqual([
      expect.objectContaining({
        id: "c1",
        source_id: "s1",
        fsrs_state: "review",
        stability: 3.5,
        due_at: "2026-11-09T00:00:00Z",
        reps: 2,
        take_id: null,
        take_version_id: null,
      }),
    ]);
  });

  // 0011 only adds tables and columns too; the same guard against a cards rebuild that drops a schedule.
  it("the 0011_search_ask migration keeps an existing card and its schedule", () => {
    const sqlite = new Database(":memory:");
    const sqlByKey = migrations.migrations as Record<string, string>;
    const runMigration = (idx: number) => {
      for (const statement of sqlByKey[`m${String(idx).padStart(4, "0")}`].split("--> statement-breakpoint")) {
        if (statement.trim()) sqlite.exec(statement);
      }
    };
    const searchAskIdx = migrations.journal.entries.find((entry) => entry.tag === "0011_search_ask")!.idx;
    for (let idx = 0; idx < searchAskIdx; idx++) runMigration(idx);
    sqlite
      .prepare(
        "INSERT INTO cards (id, source_id, take_id, kind, question, answer, created_at, fsrs_state, stability, due_at, reps) " +
          "VALUES ('c1', 's1', NULL, 'concept', 'Q?', 'A.', 'x', 'review', 3.5, '2026-11-09T00:00:00Z', 2)",
      )
      .run();

    runMigration(searchAskIdx);

    expect(sqlite.prepare("SELECT * FROM cards").all()).toEqual([
      expect.objectContaining({
        id: "c1",
        source_id: "s1",
        fsrs_state: "review",
        stability: 3.5,
        due_at: "2026-11-09T00:00:00Z",
        reps: 2,
        take_id: null,
        conversation_id: null,
        message_id: null,
      }),
    ]);
  });

  // 0013 only adds tables and columns too; existing cards keep their schedule and read as version 1, and existing
  // versions read as Archie's (artifacts) or the owner's (take versions).
  it("the 0013_chat_edits migration keeps an existing card and its schedule", () => {
    const sqlite = new Database(":memory:");
    const sqlByKey = migrations.migrations as Record<string, string>;
    const runMigration = (idx: number) => {
      for (const statement of sqlByKey[`m${String(idx).padStart(4, "0")}`].split("--> statement-breakpoint")) {
        if (statement.trim()) sqlite.exec(statement);
      }
    };
    const chatEditsIdx = migrations.journal.entries.find((entry) => entry.tag === "0013_chat_edits")!.idx;
    for (let idx = 0; idx < chatEditsIdx; idx++) runMigration(idx);
    sqlite
      .prepare(
        "INSERT INTO cards (id, source_id, take_id, conversation_id, message_id, kind, question, answer, created_at, " +
          "fsrs_state, stability, due_at, reps) " +
          "VALUES ('c1', 's1', NULL, NULL, NULL, 'concept', 'Q?', 'A.', 'x', 'review', 3.5, '2026-11-09T00:00:00Z', 2)",
      )
      .run();
    sqlite
      .prepare(
        "INSERT INTO artifacts (id, source_id, kind, version, content, is_current, created_at) " +
          "VALUES ('a1', 's1', 'primer', 1, '{}', 1, 'x')",
      )
      .run();
    sqlite
      .prepare(
        "INSERT INTO take_versions (id, take_id, version, body, raw_body, cleaned, created_at) " +
          "VALUES ('v1', 'k1', 1, 'b', 'b', 1, 'x')",
      )
      .run();

    runMigration(chatEditsIdx);

    expect(sqlite.prepare("SELECT * FROM cards").all()).toEqual([
      expect.objectContaining({
        id: "c1",
        source_id: "s1",
        fsrs_state: "review",
        stability: 3.5,
        due_at: "2026-11-09T00:00:00Z",
        reps: 2,
        version: 1,
      }),
    ]);
    expect(sqlite.prepare("SELECT origin, instruction FROM artifacts").all()).toEqual([
      { origin: "archie", instruction: null },
    ]);
    expect(sqlite.prepare("SELECT origin FROM take_versions").all()).toEqual([{ origin: "owner" }]);
  });
});
