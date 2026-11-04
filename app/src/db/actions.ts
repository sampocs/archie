import { randomUUID } from "expo-crypto";

import type { Intent, Reaction } from "@/capture/types";
import type { DomainName } from "@/topics/domains";

import { and, eq, isNull, min, sql } from "drizzle-orm";
import type { SQLiteUpdateSetSource } from "drizzle-orm/sqlite-core";

import type { AppDb } from "./client";
import * as schema from "./schema";

// Every action writes its optimistic row(s) and its outbox entry in one transaction: a local change without its
// outbox row would never sync, and an outbox row without the change would show stale state until the next pull.

export type ActionType =
  | "add_source"
  | "retry_source"
  | "finish_source"
  | "set_prep_me"
  | "set_read"
  | "set_primer_opened"
  | "snooze"
  | "set_queue_position"
  | "go_deeper"
  | "read_later"
  | "delete_source"
  | "add_topic"
  | "rename_topic"
  | "merge_topic"
  | "remove_topic"
  | "restore_topic"
  | "set_source_topic"
  | "request_topic_primer"
  | "choose_topics"
  | "choose_episode";
export type PrimerTarget = "source" | "topic_primer";
export type ChosenTopic = { domain: DomainName; name: string; origin: "starter" | "user" };

type Tx = Parameters<Parameters<AppDb["transaction"]>[0]>[0];

const STATE_BY_INTENT: Record<Intent, string> = { finished: "consumed", queue: "queued" };

function enqueue(tx: Tx, type: ActionType, payload: Record<string, unknown>): void {
  tx.insert(schema.outbox)
    .values({
      id: randomUUID(),
      type,
      payload: JSON.stringify(payload),
      createdAt: new Date().toISOString(),
      status: "pending",
    })
    .run();
}

// Values may be SQL expressions (e.g. keep an existing read time), as drizzle's `set` allows.
function updateSource(tx: Tx, sourceId: string, values: SQLiteUpdateSetSource<typeof schema.sources>): void {
  tx.update(schema.sources)
    .set({ ...values, updatedAt: new Date().toISOString() })
    .where(eq(schema.sources.id, sourceId))
    .run();
}

// Mirrors the server's rule: one above the current top, or 0 for an empty queue.
function topQueuePosition(tx: Tx): number {
  const row = tx
    .select({ lowest: min(schema.sources.queuePosition) })
    .from(schema.sources)
    .where(and(eq(schema.sources.state, "queued"), isNull(schema.sources.deletedAt)))
    .get();
  return row?.lowest == null ? 0 : row.lowest - 1;
}

function topicDomain(tx: Tx, topicId: string): string | undefined {
  return tx.select().from(schema.topics).where(eq(schema.topics.id, topicId)).get()?.domain;
}

// Topic names are stored with their whitespace collapsed, as the server stores them.
function cleanTopicName(name: string): string {
  return name.split(/\s+/).filter(Boolean).join(" ");
}

export async function addSource(
  db: AppDb,
  input: { url: string; intent: Intent; reaction?: Reaction | null; note?: string | null; prepMe?: boolean },
): Promise<string> {
  const id = randomUUID();
  const now = new Date().toISOString();

  db.transaction((tx) => {
    tx.insert(schema.sources)
      .values({
        id,
        url: input.url,
        kind: "link",
        state: STATE_BY_INTENT[input.intent],
        intent: input.intent,
        reaction: input.reaction ?? null,
        note: input.note || null,
        prepMe: input.prepMe ? 1 : 0,
        queuePosition: input.intent === "queue" ? topQueuePosition(tx) : null,
        createdAt: now,
        updatedAt: now,
      })
      .run();

    enqueue(tx, "add_source", {
      id,
      url: input.url,
      intent: input.intent,
      // Unset options are omitted from the wire payload, not sent as null.
      ...(input.reaction ? { reaction: input.reaction } : {}),
      ...(input.note ? { note: input.note } : {}),
      ...(input.prepMe ? { prep_me: true } : {}),
    });
  });

  return id;
}

// Optimistically shows "Processing" while the retry action syncs; the server's pulled status replaces it.
export async function retrySource(db: AppDb, sourceId: string): Promise<void> {
  db.transaction((tx) => {
    tx.update(schema.sources)
      .set({ processing: "processing", processingError: null })
      .where(eq(schema.sources.id, sourceId))
      .run();
    enqueue(tx, "retry_source", { id: sourceId });
  });
}

export function finishSource(
  db: AppDb,
  input: { sourceId: string; reaction: Reaction | null; note: string | null },
): void {
  db.transaction((tx) => {
    updateSource(tx, input.sourceId, {
      state: "consumed",
      snoozedUntil: null,
      ...(input.reaction ? { reaction: input.reaction } : {}),
      ...(input.note ? { note: input.note } : {}),
      // "Parts lost me" pushes the primer to Today, as the server does.
      ...(input.reaction === "lost" ? { prepMe: 1 } : {}),
    });
    enqueue(tx, "finish_source", {
      id: input.sourceId,
      ...(input.reaction ? { reaction: input.reaction } : {}),
      ...(input.note ? { note: input.note } : {}),
    });
  });
}

export function setPrepMe(db: AppDb, sourceId: string, prepMe: boolean): void {
  db.transaction((tx) => {
    updateSource(tx, sourceId, { prepMe: prepMe ? 1 : 0 });
    enqueue(tx, "set_prep_me", { id: sourceId, prep_me: prepMe });
  });
}

export function setRead(db: AppDb, sourceId: string, read: boolean): void {
  db.transaction((tx) => {
    updateSource(tx, sourceId, { readAt: read ? new Date().toISOString() : null });
    enqueue(tx, "set_read", { id: sourceId, read });
  });
}

export function setPrimerOpened(db: AppDb, target: PrimerTarget, id: string, opened: boolean): void {
  const openedAt = opened ? new Date().toISOString() : null;
  db.transaction((tx) => {
    if (target === "source") updateSource(tx, id, { primerOpenedAt: openedAt });
    else tx.update(schema.topicPrimers).set({ openedAt }).where(eq(schema.topicPrimers.id, id)).run();
    enqueue(tx, "set_primer_opened", { target, id, opened });
  });
}

export function snooze(db: AppDb, target: PrimerTarget, id: string, until: Date | null): void {
  const snoozedUntil = until ? until.toISOString() : null;
  db.transaction((tx) => {
    if (target === "topic_primer") {
      tx.update(schema.topicPrimers).set({ snoozedUntil }).where(eq(schema.topicPrimers.id, id)).run();
    } else {
      const source = tx.select().from(schema.sources).where(eq(schema.sources.id, id)).get();
      // A snoozed queued item comes back at the top of the queue.
      const position = until && source?.state === "queued" ? { queuePosition: topQueuePosition(tx) } : {};
      updateSource(tx, id, { snoozedUntil, ...position });
    }
    enqueue(tx, "snooze", { target, id, until: snoozedUntil });
  });
}

export function setQueuePosition(db: AppDb, sourceId: string, position: number): void {
  db.transaction((tx) => {
    updateSource(tx, sourceId, { queuePosition: position });
    enqueue(tx, "set_queue_position", { id: sourceId, position });
  });
}

export function goDeeper(db: AppDb, sourceId: string): void {
  const now = new Date().toISOString();
  db.transaction((tx) => {
    updateSource(tx, sourceId, {
      state: "consumed",
      processing: "processing",
      snoozedUntil: null,
      readAt: sql`coalesce(${schema.sources.readAt}, ${now})`,
    });
    enqueue(tx, "go_deeper", { id: sourceId });
  });
}

export function readLater(db: AppDb, sourceId: string): void {
  db.transaction((tx) => {
    updateSource(tx, sourceId, { state: "queued", snoozedUntil: null, queuePosition: topQueuePosition(tx) });
    enqueue(tx, "read_later", { id: sourceId });
  });
}

export function deleteSource(db: AppDb, sourceId: string): void {
  db.transaction((tx) => {
    updateSource(tx, sourceId, { deletedAt: new Date().toISOString() });
    enqueue(tx, "delete_source", { id: sourceId });
  });
}

export function addTopic(db: AppDb, input: { domain: DomainName; name: string }): string {
  const id = randomUUID();
  const now = new Date().toISOString();
  const name = cleanTopicName(input.name);
  db.transaction((tx) => {
    // The server writes a primer for every added topic, so the page can say it's coming right away.
    tx.insert(schema.topics)
      .values({
        id,
        domain: input.domain,
        name,
        origin: "user",
        createdAt: now,
        updatedAt: now,
        primerRequestedAt: now,
      })
      .run();
    enqueue(tx, "add_topic", { id, domain: input.domain, name });
  });
  return id;
}

export function renameTopic(db: AppDb, topicId: string, name: string): void {
  const cleaned = cleanTopicName(name);
  db.transaction((tx) => {
    tx.update(schema.topics)
      .set({ name: cleaned, updatedAt: new Date().toISOString() })
      .where(eq(schema.topics.id, topicId))
      .run();
    enqueue(tx, "rename_topic", { id: topicId, name: cleaned });
  });
}

export function mergeTopic(db: AppDb, topicId: string, intoId: string): void {
  db.transaction((tx) => {
    const now = new Date().toISOString();
    const domain = topicDomain(tx, intoId);

    // An unknown target leaves the sources' domain as it was rather than blanking it.
    tx.update(schema.sources)
      .set({ topicId: intoId, updatedAt: now, ...(domain && { domain }) })
      .where(eq(schema.sources.topicId, topicId))
      .run();
    tx.update(schema.topics).set({ mergedIntoId: intoId, updatedAt: now }).where(eq(schema.topics.id, topicId)).run();
    enqueue(tx, "merge_topic", { id: topicId, into_id: intoId });
  });
}

export function removeTopic(db: AppDb, topicId: string): void {
  db.transaction((tx) => {
    const now = new Date().toISOString();
    tx.update(schema.topics).set({ removedAt: now, updatedAt: now }).where(eq(schema.topics.id, topicId)).run();

    // The server re-files these; until then they show without a topic, never under the removed one.
    tx.update(schema.sources).set({ topicId: null, updatedAt: now }).where(eq(schema.sources.topicId, topicId)).run();
    enqueue(tx, "remove_topic", { id: topicId });
  });
}

export function restoreTopic(db: AppDb, topicId: string): void {
  db.transaction((tx) => {
    tx.update(schema.topics).set({ removedAt: null, updatedAt: new Date().toISOString() }).where(eq(schema.topics.id, topicId)).run();
    enqueue(tx, "restore_topic", { id: topicId });
  });
}

export function setSourceTopic(db: AppDb, sourceId: string, topicId: string): void {
  db.transaction((tx) => {
    // An unknown topic keeps the source's existing domain.
    const domain = topicDomain(tx, topicId);
    updateSource(tx, sourceId, { topicId, ...(domain && { domain }) });
    enqueue(tx, "set_source_topic", { id: sourceId, topic_id: topicId });
  });
}

export function requestTopicPrimer(db: AppDb, topicId: string): void {
  db.transaction((tx) => {
    tx.update(schema.topics)
      .set({ primerRequestedAt: new Date().toISOString() })
      .where(eq(schema.topics.id, topicId))
      .run();
    enqueue(tx, "request_topic_primer", { id: topicId });
  });
}

export function chooseTopics(db: AppDb, topics: ChosenTopic[]): void {
  const now = new Date().toISOString();
  const rows = topics.map((topic) => ({ ...topic, id: randomUUID() }));
  db.transaction((tx) => {
    for (const row of rows) {
      tx.insert(schema.topics)
        .values({
          id: row.id,
          domain: row.domain,
          name: row.name,
          origin: row.origin,
          createdAt: now,
          updatedAt: now,
          // The server writes primers only for topics the user typed in, not for starter picks.
          primerRequestedAt: row.origin === "user" ? now : null,
        })
        .run();
    }
    enqueue(tx, "choose_topics", { topics: rows.map((row) => ({ id: row.id, domain: row.domain, name: row.name })) });
  });
}

export function chooseEpisode(db: AppDb, sourceId: string, guid: string): void {
  db.transaction((tx) => {
    updateSource(tx, sourceId, { processing: "processing", processingError: null });
    enqueue(tx, "choose_episode", { id: sourceId, guid });
  });
}
