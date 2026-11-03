import { NetworkError, UnauthorizedError } from "@/api/client";

export type OutboxEntry = { id: string; type: string; payload: unknown };
export type PushResult = { id: string; result: "applied" | "duplicate" | "rejected"; reason: string | null };
export type PulledSource = {
  id: string;
  url: string;
  title: string | null;
  kind: string;
  state: string;
  intent: string;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
};
export type PullPage = { rows: { sources: PulledSource[] }; position: number; more: boolean };

export interface SyncStore {
  pendingActions(limit: number): Promise<OutboxEntry[]>;
  removeActions(ids: string[]): Promise<void>;
  // Also sets sources.syncError for that action's source.
  rejectAction(id: string, reason: string): Promise<void>;
  getPosition(): Promise<number>;
  // Upserts rows and saves the position in one transaction.
  applyPage(page: PullPage): Promise<void>;
  setLastPushFailed(failed: boolean): Promise<void>;
}

export interface SyncTransport {
  push(actions: OutboxEntry[]): Promise<PushResult[]>;
  pull(since: number): Promise<PullPage>;
}

export type SyncOutcome = "synced" | "offline" | "unauthorized";

export const PUSH_BATCH = 50;

export async function runSync(store: SyncStore, transport: SyncTransport): Promise<SyncOutcome> {
  let pushing = true;
  try {
    await pushAll(store, transport);
    pushing = false;
    await pullAll(store, transport);
    return "synced";
  } catch (error) {
    if (error instanceof UnauthorizedError) return "unauthorized";
    if (error instanceof NetworkError) {
      // Only a failed push means local changes are stuck; a failed pull says nothing about them.
      if (pushing) await store.setLastPushFailed(true);
      return "offline";
    }
    throw error;
  }
}

async function pushAll(store: SyncStore, transport: SyncTransport): Promise<void> {
  // Push before pulling: a pull must never overwrite a local change the server hasn't seen yet.
  for (
    let batch = await store.pendingActions(PUSH_BATCH);
    batch.length > 0;
    batch = await store.pendingActions(PUSH_BATCH)
  ) {
    const results = await transport.push(batch);
    // A response that settles nothing would re-send the same batch forever.
    if (results.length === 0) throw new Error("push returned no results for a non-empty batch");

    // Results for ids outside this batch settle nothing here either, so the same batch would be re-sent.
    const batchIds = new Set(batch.map((entry) => entry.id));
    if (!results.some((result) => batchIds.has(result.id))) {
      throw new Error("push returned no results for the pushed batch");
    }

    for (const rejected of results.filter((result) => result.result === "rejected")) {
      await store.rejectAction(rejected.id, rejected.reason ?? "rejected");
    }
    await store.removeActions(results.filter((result) => result.result !== "rejected").map((result) => result.id));
  }
  await store.setLastPushFailed(false);
}

async function pullAll(store: SyncStore, transport: SyncTransport): Promise<void> {
  for (let more = true; more; ) {
    const page = await transport.pull(await store.getPosition());
    await store.applyPage(page);
    more = page.more;
  }
}

// Serializes runs: a trigger that lands mid-run is coalesced into exactly one follow-up run,
// even when the run it landed in throws (the follow-up runs, then the first error is rethrown).
export function createSyncScheduler(run: () => Promise<void>): () => Promise<void> {
  let running = false;
  let rerun = false;

  return async function trigger(): Promise<void> {
    if (running) {
      rerun = true;
      return;
    }

    running = true;
    try {
      let failure: { error: unknown } | null = null;
      do {
        rerun = false;
        try {
          await run();
        } catch (error) {
          failure ??= { error };
        }
      } while (rerun);
      if (failure) throw failure.error;
    } finally {
      running = false;
    }
  };
}
