import { asc, eq, inArray } from "drizzle-orm";

import { apiFetch } from "@/api/client";
import type { AppDb } from "@/db/client";
import * as schema from "@/db/schema";
import { getSessionEpoch } from "@/auth/sessionEpoch";

import type {
  OutboxEntry,
  PullPage,
  PushResult,
  SyncStore,
  SyncTransport,
} from "./engine";

export function createApiTransport(
  getSessionKey: () => string | null,
): SyncTransport {
  return {
    async push(actions: OutboxEntry[]): Promise<PushResult[]> {
      const response = (await apiFetch("/sync/push", {
        method: "POST",
        body: { actions },
        sessionKey: getSessionKey(),
      })) as { results: PushResult[] };
      return response.results;
    },

    async pull(since: number): Promise<PullPage> {
      return (await apiFetch(`/sync/pull?since=${since}`, {
        sessionKey: getSessionKey(),
      })) as PullPage;
    },
  };
}

// `runEpoch` is the session epoch when the sync run started. Every write is a no-op once it has changed (the user
// signed out and the local database was wiped), so a late response can't repopulate it. The check runs inside the
// transaction, and the drivers are synchronous, so nothing can slip in between the check and the write.
// Actions whose payload id is a topic row (add_topic is handled apart: its row is deleted, not re-pulled).
const TOPIC_ACTIONS = new Set([
  "rename_topic",
  "merge_topic",
  "remove_topic",
  "restore_topic",
  "request_topic_primer",
]);

// Actions whose payload id is a brief: a rejection rewinds and touches no source row.
const BRIEF_ACTIONS = new Set(["finish_brief"]);

// Actions whose payload id is a card: a rejection re-pulls the server's copy and touches no source row.
const CARD_ACTIONS = new Set(["review_card", "drop_card"]);

// Source actions whose optimistic edit a rejection must undo by re-pulling the server copy.
const REWOUND_SOURCE_ACTIONS = new Set([
  "go_deeper",
  "choose_episode",
  "queue_primer",
  "request_primer",
  "return_to_inbox",
  "set_cards_off",
  "set_favorite",
]);

export function createDbSyncStore(
  db: AppDb,
  runEpoch: number = getSessionEpoch(),
): SyncStore {
  const signedOutSinceStart = () => getSessionEpoch() !== runEpoch;

  return {
    async pendingActions(limit) {
      const rows = db
        .select()
        .from(schema.outbox)
        .where(eq(schema.outbox.status, "pending"))
        .orderBy(asc(schema.outbox.createdAt), asc(schema.outbox.id))
        .limit(limit)
        .all();
      return rows.map((row) => ({
        id: row.id,
        type: row.type,
        payload: JSON.parse(row.payload),
      }));
    },

    async removeActions(ids) {
      if (ids.length === 0) return;
      db.transaction((tx) => {
        if (signedOutSinceStart()) return;
        tx.delete(schema.outbox).where(inArray(schema.outbox.id, ids)).run();
      });
    },

    async rejectAction(id, reason) {
      db.transaction((tx) => {
        if (signedOutSinceStart()) return;
        const entry = tx
          .select()
          .from(schema.outbox)
          .where(eq(schema.outbox.id, id))
          .get();
        tx.update(schema.outbox)
          .set({ status: "rejected", error: reason })
          .where(eq(schema.outbox.id, id))
          .run();
        if (!entry) return;

        const payload = JSON.parse(entry.payload) as {
          id?: string;
          topics?: { id: string }[];
          target?: string;
        };

        // The server created none of these topics, so the optimistic rows would otherwise linger forever.
        if (entry.type === "choose_topics") {
          const topicIds = (payload.topics ?? []).map((topic) => topic.id);
          tx.delete(schema.topics)
            .where(inArray(schema.topics.id, topicIds))
            .run();
          return;
        }

        // A rejection doesn't bump the row's change_seq, so no pull would undo the optimistic edit; rewinding the
        // position makes the next pull re-send the server's topic or topic primer.
        // Source actions that change state, processing or the primer's queue entry optimistically rewind too, and
        // still surface syncError on the source below. A rejected finish_brief (a brief already closed) re-pulls the brief
        // and the newsletters it marked briefed; a rejected card action re-pulls the card's schedule or undoes its drop.
        const rowIsNotSource = TOPIC_ACTIONS.has(entry.type) || BRIEF_ACTIONS.has(entry.type) || CARD_ACTIONS.has(entry.type);
        const rewind =
          rowIsNotSource ||
          payload.target === "topic_primer" ||
          payload.target === "source_primer" ||
          REWOUND_SOURCE_ACTIONS.has(entry.type);
        if (rewind) {
          tx.update(schema.syncState)
            .set({ position: 0 })
            .where(eq(schema.syncState.id, 1))
            .run();
          if (rowIsNotSource || payload.target === "topic_primer") {
            return;
          }
        }

        // The payload carries the changed row's id; surface the failure on that row.
        const rowId = payload.id;
        if (!rowId) return;

        // The server never created this topic, so the optimistic row would otherwise linger forever.
        if (entry.type === "add_topic") {
          tx.delete(schema.topics).where(eq(schema.topics.id, rowId)).run();
          return;
        }

        // A rejected retry never started the pipeline, so undo the optimistic "processing" `retrySource` set.
        const changes =
          entry.type === "retry_source"
            ? { syncError: reason, processing: "failed" }
            : { syncError: reason };
        tx.update(schema.sources)
          .set(changes)
          .where(eq(schema.sources.id, rowId))
          .run();
      });
    },

    async getPosition() {
      const row = db
        .select()
        .from(schema.syncState)
        .where(eq(schema.syncState.id, 1))
        .get();
      return row?.position ?? 0;
    },

    async applyPage(page) {
      db.transaction((tx) => {
        if (signedOutSinceStart()) return;

        // A row (source, card, topic, topic primer or brief) with an unsent local action keeps its local copy; it returns
        // on a later pull once the push bumps its change_seq. No timestamp comparison: phone and server clocks can't be
        // trusted.
        const unsent = new Set(
          tx
            .select()
            .from(schema.outbox)
            .where(eq(schema.outbox.status, "pending"))
            .all()
            .map((entry) => (JSON.parse(entry.payload) as { id?: string }).id),
        );

        for (const source of page.rows.sources) {
          if (unsent.has(source.id)) continue;

          // Server copy wins: a push always happens first, so it already includes our local changes
          // (except actions queued mid-sync, skipped above).
          // syncError is deliberately left out of the update set.
          const values = {
            url: source.url,
            title: source.title,
            kind: source.kind,
            state: source.state,
            intent: source.intent,
            createdAt: source.created_at,
            updatedAt: source.updated_at,
            deletedAt: source.deleted_at,
            processing: source.processing,
            processingError: source.processing_error,
            reaction: source.reaction,
            note: source.note,
            mergedIntoId: source.merged_into_id,
            sender: source.sender,
            domain: source.domain,
            topicId: source.topic_id,
            imageUrl: source.image_url,
            queuePosition: source.queue_position,
            readAt: source.read_at,
            snoozedUntil: source.snoozed_until,
            primerOpenedAt: source.primer_opened_at,
            primerQueuePosition: source.primer_queue_position,
            primerSnoozedUntil: source.primer_snoozed_until,
            newsletterKind: source.newsletter_kind,
            cardsOff: source.cards_off ? 1 : 0,
            favoritedAt: source.favorited_at ?? null,
          };
          tx.insert(schema.sources)
            .values({ id: source.id, ...values })
            .onConflictDoUpdate({ target: schema.sources.id, set: values })
            .run();
        }

        for (const artifact of page.rows.artifacts) {
          const values = {
            sourceId: artifact.source_id,
            kind: artifact.kind,
            version: artifact.version,
            content: JSON.stringify(artifact.content),
            isCurrent: artifact.is_current ? 1 : 0,
            createdAt: artifact.created_at,
          };
          tx.insert(schema.artifacts)
            .values({ id: artifact.id, ...values })
            .onConflictDoUpdate({ target: schema.artifacts.id, set: values })
            .run();
        }

        for (const card of page.rows.cards) {
          if (unsent.has(card.id)) continue;
          const values = {
            sourceId: card.source_id,
            topicPrimerId: card.topic_primer_id ?? null,
            briefId: card.brief_id ?? null,
            kind: card.kind,
            question: card.question,
            answer: card.answer,
            createdAt: card.created_at,
            deletedAt: card.deleted_at,
            fsrsState: card.fsrs_state ?? "new",
            stability: card.stability ?? null,
            difficulty: card.difficulty ?? null,
            dueAt: card.due_at ?? null,
            lastReviewAt: card.last_review_at ?? null,
            reps: card.reps ?? 0,
            lapses: card.lapses ?? 0,
            expiresAt: card.expires_at ?? null,
          };
          tx.insert(schema.cards)
            .values({ id: card.id, ...values })
            .onConflictDoUpdate({ target: schema.cards.id, set: values })
            .run();
        }

        for (const topic of page.rows.topics ?? []) {
          if (unsent.has(topic.id)) continue;
          // primerRequestedAt is phone-only and deliberately left out.
          const values = {
            domain: topic.domain,
            name: topic.name,
            origin: topic.origin,
            removedAt: topic.removed_at,
            mergedIntoId: topic.merged_into_id,
            createdAt: topic.created_at,
            updatedAt: topic.updated_at,
          };
          tx.insert(schema.topics)
            .values({ id: topic.id, ...values })
            .onConflictDoUpdate({ target: schema.topics.id, set: values })
            .run();
        }

        for (const primer of page.rows.topic_primers ?? []) {
          if (unsent.has(primer.id)) continue;
          const values = {
            topicId: primer.topic_id,
            version: primer.version,
            isCurrent: primer.is_current ? 1 : 0,
            content: JSON.stringify(primer.content),
            openedAt: primer.opened_at,
            snoozedUntil: primer.snoozed_until,
            createdAt: primer.created_at,
          };
          tx.insert(schema.topicPrimers)
            .values({ id: primer.id, ...values })
            .onConflictDoUpdate({ target: schema.topicPrimers.id, set: values })
            .run();
        }

        for (const brief of page.rows.briefs ?? []) {
          if (unsent.has(brief.id)) continue;
          const values = {
            status: brief.status,
            content: brief.content == null ? null : JSON.stringify(brief.content),
            sourceIds: JSON.stringify(brief.source_ids),
            since: brief.since,
            version: brief.version,
            createdAt: brief.created_at,
            updatedAt: brief.updated_at,
            doneAt: brief.done_at,
          };
          tx.insert(schema.briefs)
            .values({ id: brief.id, ...values })
            .onConflictDoUpdate({ target: schema.briefs.id, set: values })
            .run();
        }

        tx.update(schema.syncState)
          .set({ position: page.position })
          .where(eq(schema.syncState.id, 1))
          .run();
      });
    },

    async setLastPushFailed(failed) {
      db.transaction((tx) => {
        if (signedOutSinceStart()) return;
        tx.update(schema.syncState)
          .set({ lastPushFailed: failed ? 1 : 0 })
          .where(eq(schema.syncState.id, 1))
          .run();
      });
    },
  };
}
