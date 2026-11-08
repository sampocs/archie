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
  merged_into_id: string | null;
  sender: string | null;
  domain: string | null;
  topic_id: string | null;
  image_url: string | null;
  queue_position: number | null;
  read_at: string | null;
  snoozed_until: string | null;
  primer_opened_at: string | null;
  primer_queue_position: number | null;
  primer_snoozed_until: string | null;
  newsletter_kind: string | null;
  // Absent when pulling from a server older than M6.
  cards_off?: boolean;
  favorited_at?: string | null;
  // Absent when pulling from a server older than item dates.
  published_at?: string | null;
};
export type PulledArtifact = {
  id: string;
  source_id: string;
  kind: string;
  version: number;
  content: unknown;
  is_current: boolean;
  created_at: string;
  // Absent when pulling from a server older than chat edits.
  origin?: string;
  instruction?: string | null;
};
export type PulledCard = {
  id: string;
  source_id: string | null;
  // The other origins and the FSRS state are absent when pulling from a server older than M6.
  topic_primer_id?: string | null;
  brief_id?: string | null;
  kind: string;
  question: string;
  answer: string;
  created_at: string;
  deleted_at: string | null;
  fsrs_state?: string;
  stability?: number | null;
  difficulty?: number | null;
  due_at?: string | null;
  last_review_at?: string | null;
  reps?: number;
  lapses?: number;
  expires_at?: string | null;
  // Absent when pulling from a server older than Saved piece 3.
  take_id?: string | null;
  take_version_id?: string | null;
  // Absent when pulling from a server older than M7.
  conversation_id?: string | null;
  message_id?: string | null;
  // Absent when pulling from a server older than chat edits.
  version?: number;
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
  // Absent when pulling from a server older than chat edits.
  origin?: string;
  instruction?: string | null;
};
export type PulledBrief = {
  id: string;
  status: string;
  content: unknown;
  source_ids: string[];
  since: string | null;
  version: number;
  created_at: string;
  updated_at: string;
  done_at: string | null;
};
export type PulledCollection = {
  id: string;
  name: string;
  position: number;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
};
export type PulledCollectionItem = {
  id: string;
  collection_id: string;
  url: string;
  kind: string;
  title: string | null;
  author: string | null;
  image_url: string | null;
  duration_seconds: number | null;
  note: string | null;
  metadata_status: string;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
};
export type PulledTake = {
  id: string;
  kind: string;
  title: string;
  current_version: number;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
};
export type PulledTakeVersion = {
  id: string;
  take_id: string;
  version: number;
  body: string | null;
  raw_body: string;
  cleaned: boolean;
  clean_failed: boolean;
  created_at: string;
  // Absent when pulling from a server older than chat edits.
  origin?: string;
};
export type PulledConversation = {
  id: string;
  title: string;
  about_kind: string | null;
  about_source_id: string | null;
  about_topic_primer_id: string | null;
  about_take_id: string | null;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
  change_seq: number;
};
export type PulledMessage = {
  id: string;
  conversation_id: string;
  role: string;
  text: string;
  segments: unknown[] | null;
  web_search: boolean;
  status: string;
  created_at: string;
  change_seq: number;
};
export type PulledCardVersion = {
  id: string;
  card_id: string;
  version: number;
  question: string;
  answer: string;
  origin: string;
  instruction: string | null;
  created_at: string;
  change_seq: number;
};
export type PulledEditProposal = {
  id: string;
  conversation_id: string;
  message_id: string;
  target_kind: string;
  target_id: string;
  title: string;
  description: string;
  base_version: number;
  before: unknown;
  after: unknown;
  status: string;
  applied_version: number | null;
  created_at: string;
  updated_at: string;
  change_seq: number;
};
export type PullPage = {
  rows: {
    sources: PulledSource[];
    artifacts: PulledArtifact[];
    cards: PulledCard[];
    // Absent when pulling from a server older than M4.
    topics?: PulledTopic[];
    topic_primers?: PulledTopicPrimer[];
    // Absent when pulling from a server older than M5.
    briefs?: PulledBrief[];
    // Absent when pulling from a server older than Saved piece 2.
    collections?: PulledCollection[];
    collection_items?: PulledCollectionItem[];
    // Absent when pulling from a server older than Saved piece 3.
    takes?: PulledTake[];
    take_versions?: PulledTakeVersion[];
    // Absent when pulling from a server older than M7.
    conversations?: PulledConversation[];
    messages?: PulledMessage[];
    // Absent when pulling from a server older than chat edits.
    card_versions?: PulledCardVersion[];
    edit_proposals?: PulledEditProposal[];
  };
  position: number;
  more: boolean;
};

export interface SyncStore {
  pendingActions(limit: number): Promise<OutboxEntry[]>;
  removeActions(ids: string[]): Promise<void>;
  // Also sets sources.syncError for that action's source. A rejected add_topic / choose_topics deletes its optimistic
  // topics, and a rejected create_collection / add_collection_item deletes its optimistic rows; a rejected save_take /
  // restore_take_version deletes its optimistic version (and a new take left with none) and rewinds. Any other rejected
  // topic or topic-primer action, finish_brief, a card action, a rejected update_collection / update_collection_item,
  // update_take / retry_take_cleanup, a rejected delete_conversation, and the source actions in transport's
  // REWOUND_SOURCE_ACTIONS, rewind the position so the next pull restores the server copy. No take or chat action
  // touches a source.
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
