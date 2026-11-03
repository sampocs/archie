import Database from "better-sqlite3";
import { drizzle } from "drizzle-orm/better-sqlite3";
import { eq } from "drizzle-orm";

import { NetworkError, UnauthorizedError } from "@/api/client";
import type { AppDb } from "@/db/client";
import * as schema from "@/db/schema";

import {
  createSyncScheduler,
  OutboxEntry,
  PulledSource,
  PullPage,
  PushResult,
  runSync,
  SyncStore,
  SyncTransport,
} from "./engine";
import { createDbSyncStore } from "./transport";

jest.mock("expo-crypto", () => ({ randomUUID: () => require("crypto").randomUUID() }));

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
  return Array.from({ length: count }, (_, index) => ({ id: `a${index}`, type: "add_source", payload: {} }));
}

const emptyPage = (position: number, more = false): PullPage => ({ rows: { sources: [] }, position, more });

function makeTransport(overrides: Partial<SyncTransport> = {}) {
  const calls = { pushes: [] as string[][], pulls: [] as number[] };
  const transport: SyncTransport = {
    async push(actions) {
      calls.pushes.push(actions.map((entry) => entry.id));
      return actions.map((entry): PushResult => ({ id: entry.id, result: "applied", reason: null }));
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
    expect(calls.pushes.flat()).toEqual(makeEntries(120).map((entry) => entry.id));
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

  it("throws instead of re-sending forever when no result belongs to the pushed batch", async () => {
    const { store } = makeMemoryStore(makeEntries(2));
    const { transport } = makeTransport({
      async push() {
        return [{ id: "unrelated", result: "applied", reason: null }];
      },
    });

    await expect(runSync(store, transport)).rejects.toThrow("no results for the pushed batch");
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
    const pages = [emptyPage(10, true), emptyPage(20, true), emptyPage(25, false)];
    const { transport, calls } = makeTransport({
      async push(actions) {
        order.push("push");
        return actions.map((entry): PushResult => ({ id: entry.id, result: "applied", reason: null }));
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
  const sqlite = new Database(":memory:");
  sqlite.exec(`
    CREATE TABLE sources (
      id text PRIMARY KEY NOT NULL, url text NOT NULL, title text, kind text NOT NULL, state text NOT NULL,
      intent text NOT NULL, created_at text NOT NULL, updated_at text NOT NULL, deleted_at text, sync_error text
    );
    CREATE TABLE outbox (
      id text PRIMARY KEY NOT NULL, type text NOT NULL, payload text NOT NULL, created_at text NOT NULL,
      status text NOT NULL, error text
    );
    CREATE TABLE sync_state (id integer PRIMARY KEY NOT NULL, position integer NOT NULL, last_push_failed integer NOT NULL);
    INSERT INTO sync_state VALUES (1, 0, 0);
  `);
  const db = drizzle(sqlite, { schema }) as unknown as AppDb;
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
  ...overrides,
});

describe("database SyncStore", () => {
  it("upserts a pulled row over the local copy, keeps syncError, and saves the position", async () => {
    const { db, store } = makeDbStore();
    db.insert(schema.sources)
      .values({ ...pulledSource({}), createdAt: "2026-11-01T00:00:00Z", updatedAt: "2026-11-01T00:00:00Z", syncError: "boom" })
      .run();

    await store.applyPage({
      rows: { sources: [pulledSource({ title: "Server title", state: "consumed", updated_at: "2026-11-02T00:00:00Z" })] },
      position: 42,
      more: false,
    });

    const row = db.select().from(schema.sources).where(eq(schema.sources.id, "s1")).get();
    expect(row).toMatchObject({ title: "Server title", state: "consumed", updatedAt: "2026-11-02T00:00:00Z", syncError: "boom" });
    expect(await store.getPosition()).toBe(42);
  });

  it("skips rows whose source has an unsent local action but still saves the position", async () => {
    const { db, store } = makeDbStore();
    db.insert(schema.sources)
      .values({ ...pulledSource({ title: "Local title" }), createdAt: "x", updatedAt: "x" })
      .run();
    db.insert(schema.outbox)
      .values({ id: "o1", type: "update_source", payload: JSON.stringify({ id: "s1" }), createdAt: "x", status: "pending" })
      .run();

    await store.applyPage({
      rows: { sources: [pulledSource({ title: "Server title" }), pulledSource({ id: "s3", title: "Other" })] },
      position: 9,
      more: false,
    });

    const rows = db.select().from(schema.sources).all();
    expect(rows.find((row) => row.id === "s1")?.title).toBe("Local title");
    expect(rows.find((row) => row.id === "s3")?.title).toBe("Other");
    expect(await store.getPosition()).toBe(9);
  });

  it("inserts rows it has not seen and applies tombstones", async () => {
    const { db, store } = makeDbStore();

    await store.applyPage({
      rows: { sources: [pulledSource({ id: "s2", deleted_at: "2026-11-02T00:00:00Z" })] },
      position: 1,
      more: false,
    });

    const row = db.select().from(schema.sources).where(eq(schema.sources.id, "s2")).get();
    expect(row?.deletedAt).toBe("2026-11-02T00:00:00Z");
  });

  it("returns only pending actions oldest first, and a rejection sets the source's syncError and leaves the queue", async () => {
    const { db, store } = makeDbStore();
    const outboxRow = (id: string, createdAt: string, status: "pending" | "rejected") => ({
      id,
      type: "add_source",
      payload: JSON.stringify({ id: `src-${id}` }),
      createdAt,
      status,
    });
    db.insert(schema.outbox)
      .values([outboxRow("late", "2026-11-01T00:00:02Z", "pending"), outboxRow("early", "2026-11-01T00:00:01Z", "pending"), outboxRow("old", "2026-11-01T00:00:00Z", "rejected")])
      .run();
    db.insert(schema.sources).values({ ...pulledSource({ id: "src-early" }), createdAt: "x", updatedAt: "x" }).run();

    expect((await store.pendingActions(50)).map((entry) => entry.id)).toEqual(["early", "late"]);

    await store.rejectAction("early", "bad url");

    expect((await store.pendingActions(50)).map((entry) => entry.id)).toEqual(["late"]);
    const source = db.select().from(schema.sources).where(eq(schema.sources.id, "src-early")).get();
    expect(source?.syncError).toBe("bad url");
  });
});

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
