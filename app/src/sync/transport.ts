import { asc, eq, inArray } from "drizzle-orm";

import { apiFetch } from "@/api/client";
import type { AppDb } from "@/db/client";
import * as schema from "@/db/schema";
import { getSessionEpoch } from "@/auth/sessionEpoch";

import type { OutboxEntry, PullPage, PushResult, SyncStore, SyncTransport } from "./engine";

export function createApiTransport(getSessionKey: () => string | null): SyncTransport {
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
      return (await apiFetch(`/sync/pull?since=${since}`, { sessionKey: getSessionKey() })) as PullPage;
    },
  };
}

// `runEpoch` is the session epoch when the sync run started. Every write is a no-op once it has changed (the user
// signed out and the local database was wiped), so a late response can't repopulate it. The check runs inside the
// transaction, and the drivers are synchronous, so nothing can slip in between the check and the write.
export function createDbSyncStore(db: AppDb, runEpoch: number = getSessionEpoch()): SyncStore {
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
      return rows.map((row) => ({ id: row.id, type: row.type, payload: JSON.parse(row.payload) }));
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
        const entry = tx.select().from(schema.outbox).where(eq(schema.outbox.id, id)).get();
        tx.update(schema.outbox).set({ status: "rejected", error: reason }).where(eq(schema.outbox.id, id)).run();
        if (!entry) return;

        // The payload carries the source id for source actions; surface the failure on that row.
        const sourceId = (JSON.parse(entry.payload) as { id?: string }).id;
        if (sourceId) {
          tx.update(schema.sources).set({ syncError: reason }).where(eq(schema.sources.id, sourceId)).run();
        }
      });
    },

    async getPosition() {
      const row = db.select().from(schema.syncState).where(eq(schema.syncState.id, 1)).get();
      return row?.position ?? 0;
    },

    async applyPage(page) {
      db.transaction((tx) => {
        if (signedOutSinceStart()) return;

        // A source with an unsent local action keeps its local copy; it returns on a later pull once the
        // push bumps its change_seq. No timestamp comparison: phone and server clocks can't be trusted.
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
            prepMe: source.prep_me ? 1 : 0,
            mergedIntoId: source.merged_into_id,
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
          const values = {
            sourceId: card.source_id,
            kind: card.kind,
            question: card.question,
            answer: card.answer,
            createdAt: card.created_at,
            deletedAt: card.deleted_at,
          };
          tx.insert(schema.cards)
            .values({ id: card.id, ...values })
            .onConflictDoUpdate({ target: schema.cards.id, set: values })
            .run();
        }

        tx.update(schema.syncState).set({ position: page.position }).where(eq(schema.syncState.id, 1)).run();
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
