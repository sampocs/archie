import { asc, eq, inArray, max } from "drizzle-orm";

import { apiFetch } from "@/api/client";
import type { AppDb } from "@/db/client";
import * as schema from "@/db/schema";
import { getSessionEpoch } from "@/auth/sessionEpoch";
import { cardVersionValues, proposalValues } from "@/edits/types";

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

// Actions whose payload id is a collection or a saved post: a rejection re-pulls the server's copy and touches no source.
const COLLECTION_ACTIONS = new Set(["update_collection", "update_collection_item"]);

// Actions whose payload id is a take: a rejection re-pulls the server's copy and touches no source.
const TAKE_ACTIONS = new Set(["update_take", "retry_take_cleanup"]);

// Actions whose payload id is an Ask chat: a rejection re-pulls the server's copy and touches no source.
const CONVERSATION_ACTIONS = new Set(["delete_conversation"]);

// Take actions that add a version on the phone: a rejection removes it (the server never made it).
const TAKE_VERSION_ACTIONS = new Set(["save_take", "restore_take_version"]);

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
          version_id?: string;
        };

        // The server created none of these topics, so the optimistic rows would otherwise linger forever.
        if (entry.type === "choose_topics") {
          const topicIds = (payload.topics ?? []).map((topic) => topic.id);
          tx.delete(schema.topics)
            .where(inArray(schema.topics.id, topicIds))
            .run();
          return;
        }

        // The server never created these, so the optimistic rows would otherwise linger forever.
        if (entry.type === "create_collection" && payload.id) {
          tx.delete(schema.collectionItems).where(eq(schema.collectionItems.collectionId, payload.id)).run();
          tx.delete(schema.collections).where(eq(schema.collections.id, payload.id)).run();
          return;
        }
        if (entry.type === "add_collection_item" && payload.id) {
          tx.delete(schema.collectionItems).where(eq(schema.collectionItems.id, payload.id)).run();
          return;
        }

        // The server made no version (and, for a new take, no take): drop ours, point the take back at its newest
        // remaining version (or drop a take left with none), and re-pull the server's copy.
        if (TAKE_VERSION_ACTIONS.has(entry.type) && payload.id) {
          const takeId = payload.id;
          if (payload.version_id) {
            tx.delete(schema.takeVersions).where(eq(schema.takeVersions.id, payload.version_id)).run();
          }
          const newest = tx
            .select({ version: max(schema.takeVersions.version) })
            .from(schema.takeVersions)
            .where(eq(schema.takeVersions.takeId, takeId))
            .get()?.version;
          if (newest == null) {
            tx.delete(schema.takes).where(eq(schema.takes.id, takeId)).run();
          } else {
            tx.update(schema.takes).set({ currentVersion: newest }).where(eq(schema.takes.id, takeId)).run();
          }
          tx.update(schema.syncState).set({ position: 0 }).where(eq(schema.syncState.id, 1)).run();
          return;
        }

        // A rejection doesn't bump the row's change_seq, so no pull would undo the optimistic edit; rewinding the
        // position makes the next pull re-send the server's topic or topic primer.
        // Source actions that change state, processing or the primer's queue entry optimistically rewind too, and
        // still surface syncError on the source below. A rejected finish_brief (a brief already closed) re-pulls the brief
        // and the newsletters it marked briefed; a rejected card action re-pulls the card's schedule or undoes its drop;
        // a rejected collection edit re-pulls the collection or post; a rejected take edit re-pulls the take; a rejected
        // chat delete re-pulls the chat.
        const rowIsNotSource =
          TOPIC_ACTIONS.has(entry.type) ||
          BRIEF_ACTIONS.has(entry.type) ||
          CARD_ACTIONS.has(entry.type) ||
          COLLECTION_ACTIONS.has(entry.type) ||
          TAKE_ACTIONS.has(entry.type) ||
          CONVERSATION_ACTIONS.has(entry.type);
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

        // A row (source, card, topic, topic primer, brief, collection, saved post, take, the take version an action
        // made or changed, or a chat) with an unsent local action keeps its local copy; it returns on a later pull
        // once the push bumps its change_seq. No timestamp comparison: phone and server clocks can't be trusted.
        const unsent = new Set(
          tx
            .select()
            .from(schema.outbox)
            .where(eq(schema.outbox.status, "pending"))
            .all()
            .flatMap((entry) => {
              const payload = JSON.parse(entry.payload) as { id?: string; version_id?: string };
              return [payload.id, payload.version_id];
            }),
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
            publishedAt: source.published_at ?? null,
            confirmUrl: source.confirm_url ?? null,
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
            origin: artifact.origin ?? "archie",
            instruction: artifact.instruction ?? null,
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
            takeId: card.take_id ?? null,
            takeVersionId: card.take_version_id ?? null,
            conversationId: card.conversation_id ?? null,
            messageId: card.message_id ?? null,
            version: card.version ?? 1,
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
            origin: primer.origin ?? "archie",
            instruction: primer.instruction ?? null,
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

        for (const collection of page.rows.collections ?? []) {
          if (unsent.has(collection.id)) continue;
          const values = {
            name: collection.name,
            position: collection.position,
            createdAt: collection.created_at,
            updatedAt: collection.updated_at,
            deletedAt: collection.deleted_at,
          };
          tx.insert(schema.collections)
            .values({ id: collection.id, ...values })
            .onConflictDoUpdate({ target: schema.collections.id, set: values })
            .run();
        }

        for (const item of page.rows.collection_items ?? []) {
          if (unsent.has(item.id)) continue;
          const values = {
            collectionId: item.collection_id,
            url: item.url,
            kind: item.kind,
            title: item.title,
            author: item.author,
            imageUrl: item.image_url,
            durationSeconds: item.duration_seconds,
            note: item.note,
            metadataStatus: item.metadata_status,
            createdAt: item.created_at,
            updatedAt: item.updated_at,
            deletedAt: item.deleted_at,
          };
          tx.insert(schema.collectionItems)
            .values({ id: item.id, ...values })
            .onConflictDoUpdate({ target: schema.collectionItems.id, set: values })
            .run();
        }

        for (const take of page.rows.takes ?? []) {
          if (unsent.has(take.id)) continue;
          const values = {
            kind: take.kind,
            title: take.title,
            currentVersion: take.current_version,
            createdAt: take.created_at,
            updatedAt: take.updated_at,
            deletedAt: take.deleted_at,
          };
          tx.insert(schema.takes)
            .values({ id: take.id, ...values })
            .onConflictDoUpdate({ target: schema.takes.id, set: values })
            .run();
        }

        for (const version of page.rows.take_versions ?? []) {
          if (unsent.has(version.id)) continue;
          const values = {
            takeId: version.take_id,
            version: version.version,
            body: version.body,
            rawBody: version.raw_body,
            cleaned: version.cleaned ? 1 : 0,
            cleanFailed: version.clean_failed ? 1 : 0,
            createdAt: version.created_at,
            origin: version.origin ?? "owner",
          };
          tx.insert(schema.takeVersions)
            .values({ id: version.id, ...values })
            .onConflictDoUpdate({ target: schema.takeVersions.id, set: values })
            .run();
        }

        for (const conversation of page.rows.conversations ?? []) {
          if (unsent.has(conversation.id)) continue;
          const values = {
            title: conversation.title,
            aboutKind: conversation.about_kind,
            aboutSourceId: conversation.about_source_id,
            aboutTopicPrimerId: conversation.about_topic_primer_id,
            aboutTakeId: conversation.about_take_id,
            createdAt: conversation.created_at,
            updatedAt: conversation.updated_at,
            deletedAt: conversation.deleted_at,
          };
          tx.insert(schema.conversations)
            .values({ id: conversation.id, ...values })
            .onConflictDoUpdate({ target: schema.conversations.id, set: values })
            .run();
        }

        for (const message of page.rows.messages ?? []) {
          const values = {
            conversationId: message.conversation_id,
            role: message.role,
            text: message.text,
            segments: message.segments === null ? null : JSON.stringify(message.segments),
            webSearch: message.web_search ? 1 : 0,
            status: message.status,
            createdAt: message.created_at,
          };
          tx.insert(schema.messages)
            .values({ id: message.id, ...values })
            .onConflictDoUpdate({ target: schema.messages.id, set: values })
            .run();
        }

        for (const version of page.rows.card_versions ?? []) {
          const values = cardVersionValues(version);
          tx.insert(schema.cardVersions)
            .values({ id: version.id, ...values })
            .onConflictDoUpdate({ target: schema.cardVersions.id, set: values })
            .run();
        }

        // Proposals change only through the edit routes, whose answer is stored at once (edits/api.ts), so a pulled
        // row is never older than what the phone shows.
        for (const proposal of page.rows.edit_proposals ?? []) {
          const values = proposalValues(proposal);
          tx.insert(schema.editProposals)
            .values({ id: proposal.id, ...values })
            .onConflictDoUpdate({ target: schema.editProposals.id, set: values })
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
