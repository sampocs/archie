import { ClientError, NetworkError, UnauthorizedError } from "@/api/client";

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
  processing: string;
  processing_error: string | null;
  reaction: string | null;
  note: string | null;
  prep_me: boolean;
  merged_into_id: string | null;
  sender: string | null;
  domain: string | null;
  topic_id: string | null;
  image_url: string | null;
  queue_position: number | null;
  read_at: string | null;
  snoozed_until: string | null;
  primer_opened_at: string | null;
  newsletter_kind: string | null;
};
export type PulledArtifact = {
  id: string;
  source_id: string;
  kind: string;
  version: number;
  content: unknown;
  is_current: boolean;
  created_at: string;
};
export type PulledCard = {
  id: string;
  source_id: string;
  kind: string;
  question: string;
  answer: string;
  created_at: string;
  deleted_at: string | null;
};
export type PulledTopic = {
  id: string;
  domain: string;
  name: string;
  origin: string;
  removed_at: string | null;
  merged_into_id: string | null;
  created_at: string;
  updated_at: string;
};
export type PulledTopicPrimer = {
  id: string;
  topic_id: string;
  version: number;
  is_current: boolean;
  content: unknown;
  opened_at: string | null;
  snoozed_until: string | null;
  created_at: string;
};
export type PullPage = {
  rows: {
    sources: PulledSource[];
    artifacts: PulledArtifact[];
    cards: PulledCard[];
    topics: PulledTopic[];
    topic_primers: PulledTopicPrimer[];
  };
  position: number;
  more: boolean;
};

export interface SyncStore {
  pendingActions(limit: number): Promise<OutboxEntry[]>;
  removeActions(ids: string[]): Promise<void>;
  // Also sets sources.syncError for that action's source. A rejected add_topic / choose_topics deletes its optimistic
  // topics; any other rejected topic or topic-primer action rewinds the position so the next pull restores the server copy.
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

// `onPushed` fires once local changes reached the server, so the caller can pull again soon for what the server
// derives from them (e.g. a title) instead of waiting for the next poll.
export async function runSync(
  store: SyncStore,
  transport: SyncTransport,
  onPushed: () => void = () => undefined,
): Promise<SyncOutcome> {
  let pushing = true;
  try {
    if ((await pushAll(store, transport)) > 0) onPushed();
    pushing = false;
    await pullAll(store, transport);
    return "synced";
  } catch (error) {
    if (error instanceof UnauthorizedError) return "unauthorized";
    // A refused push (4xx) leaves local changes just as stuck as an unreachable server, and retrying won't
    // unstick them; surface it as waiting rather than stalling silently.
    if (pushing && (error instanceof NetworkError || error instanceof ClientError)) {
      await store.setLastPushFailed(true);
      return "offline";
    }
    // A failed pull says nothing about local changes.
    if (error instanceof NetworkError) return "offline";
    throw error;
  }
}

// Returns how many actions were sent.
async function pushAll(store: SyncStore, transport: SyncTransport): Promise<number> {
  let sent = 0;
  // Push before pulling: a pull must never overwrite a local change the server hasn't seen yet.
  for (
    let batch = await store.pendingActions(PUSH_BATCH);
    batch.length > 0;
    batch = await store.pendingActions(PUSH_BATCH)
  ) {
    const results = await transport.push(batch);
    sent += batch.length;
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
  return sent;
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
