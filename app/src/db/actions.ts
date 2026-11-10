import { randomUUID } from "expo-crypto";

import type { Intent, Reaction } from "@/capture/types";
import { wireState, type FsrsFields, type GradedBy, type ReviewGrade } from "@/review/types";
import { MAX_TAKE_BODY_LENGTH, MAX_TAKE_TITLE_LENGTH, saveMakesVersion, type TakeKind } from "@/takes/takes";
import type { DomainName } from "@/topics/domains";

import { and, eq, inArray, isNotNull, isNull, max, min, sql } from "drizzle-orm";
import type { SQLiteUpdateSetSource } from "drizzle-orm/sqlite-core";

import type { AppDb } from "./client";
import * as schema from "./schema";

// Every action writes its optimistic row(s) and its outbox entry in one transaction: a local change without its
// outbox row would never sync, and an outbox row without the change would show stale state until the next pull.

export type ActionType =
  | "add_source"
  | "retry_source"
  | "finish_source"
  | "set_read"
  | "set_primer_opened"
  | "snooze"
  | "set_queue_position"
  | "go_deeper"
  | "queue_primer"
  | "request_primer"
  | "return_to_inbox"
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
  | "choose_episode"
  | "finish_brief"
  | "review_card"
  | "drop_card"
  | "set_cards_off"
  | "request_news_quiz"
  | "set_favorite"
  | "refresh_note"
  | "skip_note"
  | "create_collection"
  | "update_collection"
  | "add_collection_item"
  | "update_collection_item"
  | "save_take"
  | "update_take"
  | "restore_take_version"
  | "retry_take_cleanup"
  | "delete_conversation"
  | "set_sender_status";
// What the owner decides about a newsletter sender.
export type SenderStatus = "allowed" | "blocked";
export type PrimerTarget = "source" | "topic_primer";
// What a snooze applies to: a source, a topic primer, or a source's queued primer.
export type SnoozeTarget = PrimerTarget | "source_primer";
// Which queue entry a move repositions: the source itself or its queued primer.
export type QueueTarget = "source" | "source_primer";
export type ChosenTopic = { domain: DomainName; name: string; origin: "starter" | "user" };
export type ReviewInput = {
  cardId: string;
  grade: ReviewGrade;
  gradedBy: GradedBy;
  answer: string | null;
  missing: string | null;
  wasDue: boolean;
  reviewedAt: Date;
  stateBefore: FsrsFields;
  stateAfter: FsrsFields;
  replacesReviewId?: string | null;
};

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

// Mirrors the server's rule: one above the current top, or 0 for an empty queue. Queued sources and queued
// primers share one position space.
function topQueuePosition(tx: Tx): number {
  const sourceTop = tx
    .select({ lowest: min(schema.sources.queuePosition) })
    .from(schema.sources)
    .where(and(eq(schema.sources.state, "queued"), isNull(schema.sources.deletedAt)))
    .get()?.lowest;
  const primerTop = tx
    .select({ lowest: min(schema.sources.primerQueuePosition) })
    .from(schema.sources)
    .where(and(isNotNull(schema.sources.primerQueuePosition), isNull(schema.sources.deletedAt)))
    .get()?.lowest;
  const tops = [sourceTop, primerTop].filter((top): top is number => top != null);
  return tops.length === 0 ? 0 : Math.min(...tops) - 1;
}

// Queueing a newsletter's primer also writes it when it has none and nothing is running, as the server does; the
// pulled status replaces the optimistic "processing".
function primerQueuedValues(tx: Tx, sourceId: string): SQLiteUpdateSetSource<typeof schema.sources> {
  const source = tx.select().from(schema.sources).where(eq(schema.sources.id, sourceId)).get();
  const values = { primerQueuePosition: topQueuePosition(tx), primerSnoozedUntil: null };
  if (source?.kind !== "newsletter" || source.processing === "pending" || source.processing === "processing") {
    return values;
  }
  return hasPrimer(tx, sourceId) ? values : { ...values, processing: "processing", processingError: null };
}

function hasPrimer(tx: Tx, sourceId: string): boolean {
  const primer = tx
    .select({ id: schema.artifacts.id })
    .from(schema.artifacts)
    .where(
      and(
        eq(schema.artifacts.sourceId, sourceId),
        eq(schema.artifacts.kind, "primer"),
        eq(schema.artifacts.isCurrent, 1),
      ),
    )
    .get();
  return primer !== undefined;
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
  input: { url: string; intent: Intent; reaction?: Reaction | null; note?: string | null; queuePrimer?: boolean },
): Promise<string> {
  const id = randomUUID();
  const now = new Date().toISOString();
  // The server accepts a queued primer only with the queued intent.
  const queuePrimer = input.intent === "queue" && Boolean(input.queuePrimer);

  db.transaction((tx) => {
    const top = topQueuePosition(tx);
    tx.insert(schema.sources)
      .values({
        id,
        url: input.url,
        kind: "link",
        state: STATE_BY_INTENT[input.intent],
        intent: input.intent,
        reaction: input.reaction ?? null,
        note: input.note || null,
        queuePosition: input.intent === "queue" ? top : null,
        // Optimistically just above the item, so it's read first; the pulled row has the server's position.
        primerQueuePosition: queuePrimer ? top - 1 : null,
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
      ...(queuePrimer ? { queue_primer: true } : {}),
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
  input: { sourceId: string; reaction: Reaction | null; note: string | null; queuePrimer?: boolean },
): void {
  db.transaction((tx) => {
    const source = tx.select().from(schema.sources).where(eq(schema.sources.id, input.sourceId)).get();
    // A finished newsletter is analyzed again so it gets cards. The phone can't see the server's jobs, so it only
    // shows that for a ready one; for one still processing the server decides and the next pull shows it.
    const reanalyze = source?.kind === "newsletter" && source.processing === "ready" ? { processing: "processing", processingError: null } : {};
    updateSource(tx, input.sourceId, {
      state: "consumed",
      snoozedUntil: null,
      ...(input.reaction ? { reaction: input.reaction } : {}),
      ...(input.note ? { note: input.note } : {}),
      ...(input.queuePrimer ? primerQueuedValues(tx, input.sourceId) : {}),
      ...reanalyze,
    });
    enqueue(tx, "finish_source", {
      id: input.sourceId,
      ...(input.reaction ? { reaction: input.reaction } : {}),
      ...(input.note ? { note: input.note } : {}),
      ...(input.queuePrimer ? { queue_primer: true } : {}),
    });
  });
}

/** Puts the source's primer in the queue as its own entry (at the top), or takes it out. */
export function queuePrimer(db: AppDb, sourceId: string, queued: boolean): void {
  db.transaction((tx) => {
    const values = queued ? primerQueuedValues(tx, sourceId) : { primerQueuePosition: null };
    updateSource(tx, sourceId, values);
    enqueue(tx, "queue_primer", { id: sourceId, queued });
  });
}

/** "Mark as done" on a queued primer: it leaves the queue and counts as read. */
export function finishPrimer(db: AppDb, sourceId: string): void {
  db.transaction((tx) => {
    updateSource(tx, sourceId, { primerQueuePosition: null, primerOpenedAt: new Date().toISOString() });
    enqueue(tx, "queue_primer", { id: sourceId, queued: false });
    enqueue(tx, "set_primer_opened", { target: "source", id: sourceId, opened: true });
  });
}

/** A newsletter's primer, written on request; the button reads "Writing primer…" until it syncs. */
export function requestPrimer(db: AppDb, sourceId: string): void {
  db.transaction((tx) => {
    updateSource(tx, sourceId, { processing: "processing", processingError: null });
    enqueue(tx, "request_primer", { id: sourceId });
  });
}

/** Undoes "Add to queue" on a newsletter: back to the inbox, out of the queue. */
export function returnToInbox(db: AppDb, sourceId: string): void {
  db.transaction((tx) => {
    updateSource(tx, sourceId, { state: "inbox", queuePosition: null });
    enqueue(tx, "return_to_inbox", { id: sourceId });
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

export function snooze(db: AppDb, target: SnoozeTarget, id: string, until: Date | null): void {
  const snoozedUntil = until ? until.toISOString() : null;
  db.transaction((tx) => {
    if (target === "topic_primer") {
      tx.update(schema.topicPrimers).set({ snoozedUntil }).where(eq(schema.topicPrimers.id, id)).run();
    } else if (target === "source_primer") {
      const source = tx.select().from(schema.sources).where(eq(schema.sources.id, id)).get();
      // A snoozed queued primer comes back at the top of the queue, like a source.
      const queued = until && source?.primerQueuePosition != null;
      const position = queued ? { primerQueuePosition: topQueuePosition(tx) } : {};
      updateSource(tx, id, { primerSnoozedUntil: snoozedUntil, ...position });
    } else {
      const source = tx.select().from(schema.sources).where(eq(schema.sources.id, id)).get();
      // A snoozed queued item comes back at the top of the queue.
      const position = until && source?.state === "queued" ? { queuePosition: topQueuePosition(tx) } : {};
      updateSource(tx, id, { snoozedUntil, ...position });
    }
    enqueue(tx, "snooze", { target, id, until: snoozedUntil });
  });
}

export function setQueuePosition(db: AppDb, sourceId: string, position: number, target: QueueTarget = "source"): void {
  db.transaction((tx) => {
    updateSource(tx, sourceId, target === "source" ? { queuePosition: position } : { primerQueuePosition: position });
    enqueue(tx, "set_queue_position", { id: sourceId, position, target });
  });
}

export function goDeeper(db: AppDb, sourceId: string): void {
  const now = new Date().toISOString();
  db.transaction((tx) => {
    updateSource(tx, sourceId, {
      state: "consumed",
      processing: "processing",
      snoozedUntil: null,
      // The server's go_deeper turns cards back on, so the phone shows the same before the next pull.
      cardsOff: 0,
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

const sameSender = (first: string | null, second: string | null) =>
  Boolean(first?.trim()) && first?.trim().toLowerCase() === second?.trim().toLowerCase();

/**
 * Allow or Block the sender of a newsletter waiting on that decision. Locally it takes effect on the tapped source and
 * on every other pending source from the same sender (same display name, ignoring case and padding, or same address),
 * so their cards go at once: Allow un-pends them and shows them processing, Block deletes them. The server applies the
 * same decision to every identifier it knows, and the next pull corrects whatever this missed.
 */
export function judgeSender(db: AppDb, sourceId: string, status: SenderStatus): void {
  db.transaction((tx) => {
    const tapped = tx.select().from(schema.sources).where(eq(schema.sources.id, sourceId)).get();
    const pending = tx
      .select()
      .from(schema.sources)
      .where(and(eq(schema.sources.senderPending, true), isNull(schema.sources.deletedAt)))
      .all();
    const affected = pending.filter(
      (source) =>
        source.id === sourceId ||
        (tapped !== undefined &&
          (sameSender(source.sender, tapped.sender) || sameSender(source.senderAddress, tapped.senderAddress))),
    );
    const effect: SQLiteUpdateSetSource<typeof schema.sources> =
      status === "allowed"
        ? { senderPending: false, processing: "pending" }
        : { deletedAt: new Date().toISOString() };
    for (const source of affected) updateSource(tx, source.id, effect);

    enqueue(tx, "set_sender_status", { source_id: sourceId, status });
  });
}

/** Unblock (or re-block) a sender from Settings. */
export function setSenderStatus(db: AppDb, senderId: string, status: SenderStatus): void {
  db.transaction((tx) => {
    tx.update(schema.newsletterSenders)
      .set({ status, updatedAt: new Date().toISOString() })
      .where(eq(schema.newsletterSenders.id, senderId))
      .run();
    enqueue(tx, "set_sender_status", { sender_id: senderId, status });
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

/**
 * "Done ✓" on the brief: it closes, and the newsletters it covers that are still in the inbox become briefed (queued
 * or finished ones are left alone, as the server does). It sends the newsletters this brief showed, so one that landed
 * while the owner was reading stays unbriefed and goes into the next brief.
 */
export function finishBrief(db: AppDb, briefId: string): void {
  db.transaction((tx) => {
    const brief = tx.select().from(schema.briefs).where(eq(schema.briefs.id, briefId)).get();
    if (!brief) return;
    const now = new Date().toISOString();

    tx.update(schema.briefs)
      .set({ status: "done", doneAt: now, updatedAt: now })
      .where(eq(schema.briefs.id, briefId))
      .run();

    const sourceIds = JSON.parse(brief.sourceIds) as string[];
    tx.update(schema.sources)
      .set({ state: "briefed", updatedAt: now })
      .where(and(inArray(schema.sources.id, sourceIds), eq(schema.sources.state, "inbox")))
      .run();
    enqueue(tx, "finish_brief", { id: briefId, source_ids: sourceIds });
  });
}

/** Logs a graded answer and schedules the card at once (offline too); the server keeps the latest review's state. */
export function reviewCard(db: AppDb, input: ReviewInput): string {
  const reviewId = randomUUID();
  const reviewedAt = input.reviewedAt.toISOString();
  db.transaction((tx) => {
    tx.insert(schema.reviews)
      .values({
        id: reviewId,
        cardId: input.cardId,
        grade: input.grade,
        gradedBy: input.gradedBy,
        answer: input.answer,
        missing: input.missing,
        wasDue: input.wasDue ? 1 : 0,
        reviewedAt,
        stateBefore: JSON.stringify(input.stateBefore),
        stateAfter: JSON.stringify(input.stateAfter),
        replacesReviewId: input.replacesReviewId ?? null,
      })
      .run();
    tx.update(schema.cards).set(input.stateAfter).where(eq(schema.cards.id, input.cardId)).run();
    enqueue(tx, "review_card", {
      id: input.cardId,
      review_id: reviewId,
      grade: input.grade,
      graded_by: input.gradedBy,
      answer: input.answer,
      missing: input.missing,
      was_due: input.wasDue,
      reviewed_at: reviewedAt,
      state_before: wireState(input.stateBefore),
      state_after: wireState(input.stateAfter),
      replaces_review_id: input.replacesReviewId ?? null,
    });
  });
  return reviewId;
}

/** Drop (in review) and Remove (on the item page): the card goes, and the server saves a "not this" preference. */
export function dropCard(db: AppDb, cardId: string): void {
  db.transaction((tx) => {
    tx.update(schema.cards).set({ deletedAt: new Date().toISOString() }).where(eq(schema.cards.id, cardId)).run();
    enqueue(tx, "drop_card", { id: cardId });
  });
}

/** "No cards for this" retires the source's cards; turning cards back on re-runs analyze, as the server does. */
export function setCardsOff(db: AppDb, sourceId: string, off: boolean): void {
  db.transaction((tx) => {
    if (off) {
      updateSource(tx, sourceId, { cardsOff: 1 });
      tx.update(schema.cards)
        .set({ deletedAt: new Date().toISOString() })
        .where(and(eq(schema.cards.sourceId, sourceId), isNull(schema.cards.deletedAt)))
        .run();
    } else {
      updateSource(tx, sourceId, { cardsOff: 0, processing: "processing", processingError: null });
    }
    enqueue(tx, "set_cards_off", { id: sourceId, off });
  });
}

/** Stars or unstars a source; starring again keeps the first star's time, as the server does. */
export function setFavorite(db: AppDb, sourceId: string, favorited: boolean): void {
  db.transaction((tx) => {
    const favoritedAt = favorited ? sql`coalesce(${schema.sources.favoritedAt}, ${new Date().toISOString()})` : null;
    updateSource(tx, sourceId, { favoritedAt });
    enqueue(tx, "set_favorite", { id: sourceId, favorited });
  });
}

/**
 * Marks a note refreshed from Bear (consuming it); `counted` says whether the refresh came from the queue, and
 * `makeCards` false means the owner makes its cards in an Ask chat rather than the server writing them.
 */
export function refreshNote(db: AppDb, sourceId: string, counted: boolean, makeCards: boolean): void {
  db.transaction((tx) => {
    const at = new Date().toISOString();
    updateSource(tx, sourceId, { refreshedAt: at, refreshedFromQueue: counted ? 1 : 0, state: "consumed" });
    // make_cards false: the owner makes the cards in an Ask chat, so the server queues none.
    enqueue(tx, "refresh_note", { id: sourceId, counted, at, make_cards: makeCards });
  });
}

/** Dismisses a note's refresh prompt without refreshing it. */
export function skipNote(db: AppDb, sourceId: string): void {
  db.transaction((tx) => {
    const at = new Date().toISOString();
    updateSource(tx, sourceId, { refreshSkippedAt: at });
    enqueue(tx, "skip_note", { id: sourceId, at });
  });
}

export const MAX_COLLECTION_NAME_LENGTH = 100;

// Stored as the server stores it (whitespace collapsed), and cut to its limit so a typed name is never rejected.
function cleanCollectionName(name: string): string {
  // By code point, so an emoji is never cut in half (a lone surrogate cannot be encoded by the server).
  const collapsed = name.split(/\s+/).filter(Boolean).join(" ");
  return Array.from(collapsed).slice(0, MAX_COLLECTION_NAME_LENGTH).join("");
}

// A new collection goes after the last live one, as on the server.
function endCollectionPosition(tx: Tx): number {
  const last = tx
    .select({ highest: max(schema.collections.position) })
    .from(schema.collections)
    .where(isNull(schema.collections.deletedAt))
    .get()?.highest;
  return last == null ? 0 : last + 1;
}

function updateCollectionItem(tx: Tx, itemId: string, values: SQLiteUpdateSetSource<typeof schema.collectionItems>): void {
  tx.update(schema.collectionItems)
    .set({ ...values, updatedAt: new Date().toISOString() })
    .where(eq(schema.collectionItems.id, itemId))
    .run();
}

/** Makes an empty collection at the end of the list; returns its id. */
export function createCollection(db: AppDb, name: string): string {
  const id = randomUUID();
  const now = new Date().toISOString();
  const cleaned = cleanCollectionName(name);
  db.transaction((tx) => {
    tx.insert(schema.collections)
      .values({ id, name: cleaned, position: endCollectionPosition(tx), createdAt: now, updatedAt: now })
      .run();
    enqueue(tx, "create_collection", { id, name: cleaned });
  });
  return id;
}

export function renameCollection(db: AppDb, collectionId: string, name: string): void {
  const cleaned = cleanCollectionName(name);
  db.transaction((tx) => {
    tx.update(schema.collections)
      .set({ name: cleaned, updatedAt: new Date().toISOString() })
      .where(eq(schema.collections.id, collectionId))
      .run();
    enqueue(tx, "update_collection", { id: collectionId, name: cleaned });
  });
}

/** Deletes a collection and, as the server does, every post in it. */
export function deleteCollection(db: AppDb, collectionId: string): void {
  const now = new Date().toISOString();
  db.transaction((tx) => {
    tx.update(schema.collections)
      .set({ deletedAt: now, updatedAt: now })
      .where(eq(schema.collections.id, collectionId))
      .run();
    tx.update(schema.collectionItems)
      .set({ deletedAt: now, updatedAt: now })
      .where(and(eq(schema.collectionItems.collectionId, collectionId), isNull(schema.collectionItems.deletedAt)))
      .run();
    enqueue(tx, "update_collection", { id: collectionId, deleted: true });
  });
}

/** Saves a link into a collection (never as a source); the server fills in its preview. Returns the post's id. */
export function addCollectionItem(db: AppDb, input: { collectionId: string; url: string }): string {
  const id = randomUUID();
  const now = new Date().toISOString();
  db.transaction((tx) => {
    // "link" until the pulled row carries the server's x / youtube / link, as addSource does for sources.
    tx.insert(schema.collectionItems)
      .values({ id, collectionId: input.collectionId, url: input.url, kind: "link", createdAt: now, updatedAt: now })
      .run();
    enqueue(tx, "add_collection_item", { id, collection_id: input.collectionId, url: input.url });
  });
  return id;
}

/** A blank note clears it. */
export function editCollectionItemNote(db: AppDb, itemId: string, note: string): void {
  const cleaned = note.trim() || null;
  db.transaction((tx) => {
    updateCollectionItem(tx, itemId, { note: cleaned });
    enqueue(tx, "update_collection_item", { id: itemId, note: cleaned });
  });
}

export function moveCollectionItem(db: AppDb, itemId: string, collectionId: string): void {
  db.transaction((tx) => {
    updateCollectionItem(tx, itemId, { collectionId });
    enqueue(tx, "update_collection_item", { id: itemId, collection_id: collectionId });
  });
}

export function removeCollectionItem(db: AppDb, itemId: string): void {
  db.transaction((tx) => {
    updateCollectionItem(tx, itemId, { deletedAt: new Date().toISOString() });
    enqueue(tx, "update_collection_item", { id: itemId, deleted: true });
  });
}

/** Sent when Today opens on a Sunday online; the server makes the week's quiz once, if a brief was Done. */
export function requestNewsQuiz(db: AppDb, weekStart: string): void {
  db.transaction((tx) => enqueue(tx, "request_news_quiz", { week_start: weekStart }));
}

/** The answer "What I care about…" rewrote; the server already saved it, so nothing is queued. */
export function setCardAnswer(db: AppDb, cardId: string, answer: string): void {
  db.update(schema.cards).set({ answer }).where(eq(schema.cards.id, cardId)).run();
}

export { MAX_TAKE_BODY_LENGTH, MAX_TAKE_TITLE_LENGTH };

// Stored as the server stores it (whitespace collapsed), cut by code point so a typed title is never rejected.
function cleanTakeTitle(title: string): string {
  const collapsed = title.split(/\s+/).filter(Boolean).join(" ");
  return Array.from(collapsed).slice(0, MAX_TAKE_TITLE_LENGTH).join("");
}

function currentTakeVersion(tx: Tx, takeId: string) {
  const take = tx.select().from(schema.takes).where(eq(schema.takes.id, takeId)).get();
  if (!take) return undefined;
  return tx
    .select()
    .from(schema.takeVersions)
    .where(and(eq(schema.takeVersions.takeId, takeId), eq(schema.takeVersions.version, take.currentVersion)))
    .get();
}

// The take's next version, as the server will number it; the take then shows it.
function insertTakeVersion(
  tx: Tx,
  input: { takeId: string; versionId: string; body: string | null; rawBody: string; cleaned: boolean; origin: string; now: string },
): void {
  const take = tx.select().from(schema.takes).where(eq(schema.takes.id, input.takeId)).get();
  if (!take) return;
  const version = take.currentVersion + 1;
  tx.insert(schema.takeVersions)
    .values({
      id: input.versionId,
      takeId: input.takeId,
      version,
      body: input.body,
      rawBody: input.rawBody,
      cleaned: input.cleaned ? 1 : 0,
      cleanFailed: 0,
      origin: input.origin,
      createdAt: input.now,
    })
    .run();
  tx.update(schema.takes)
    .set({ currentVersion: version, updatedAt: input.now })
    .where(eq(schema.takes.id, input.takeId))
    .run();
}

/**
 * Writes a new take (`id: null`) or saves an edit. A new version is made only when the server will make one
 * (`saveMakesVersion`); the take's old cards stay until the server's new ones replace them. Returns the take's id.
 */
export function saveTake(
  db: AppDb,
  input: { id: string | null; kind: TakeKind; title: string; body: string; clean: boolean },
): string {
  const id = input.id ?? randomUUID();
  const versionId = randomUUID();
  const now = new Date().toISOString();
  const title = cleanTakeTitle(input.title);
  const body = input.body.trim();
  db.transaction((tx) => {
    const existing = tx.select().from(schema.takes).where(eq(schema.takes.id, id)).get();
    if (existing) {
      tx.update(schema.takes).set({ kind: input.kind, title, updatedAt: now }).where(eq(schema.takes.id, id)).run();
    } else {
      tx.insert(schema.takes)
        .values({ id, kind: input.kind, title, currentVersion: 0, createdAt: now, updatedAt: now })
        .run();
    }

    if (saveMakesVersion(currentTakeVersion(tx, id) ?? null, { body, clean: input.clean })) {
      insertTakeVersion(tx, {
        takeId: id,
        versionId,
        body: input.clean ? null : body,
        rawBody: body,
        cleaned: input.clean,
        origin: "owner",
        now,
      });
    }
    enqueue(tx, "save_take", { id, version_id: versionId, kind: input.kind, title, body, clean: input.clean });
  });
  return id;
}

export function changeTakeKind(db: AppDb, takeId: string, kind: TakeKind): void {
  db.transaction((tx) => {
    tx.update(schema.takes).set({ kind, updatedAt: new Date().toISOString() }).where(eq(schema.takes.id, takeId)).run();
    enqueue(tx, "update_take", { id: takeId, kind });
  });
}

/** Deletes a take and, as the server does, takes its cards out of review. */
export function deleteTake(db: AppDb, takeId: string): void {
  const now = new Date().toISOString();
  db.transaction((tx) => {
    tx.update(schema.takes).set({ deletedAt: now, updatedAt: now }).where(eq(schema.takes.id, takeId)).run();
    tx.update(schema.cards)
      .set({ deletedAt: now })
      .where(and(eq(schema.cards.takeId, takeId), isNull(schema.cards.deletedAt)))
      .run();
    enqueue(tx, "update_take", { id: takeId, deleted: true });
  });
}

/** Deletes a saved chat (cards made from it stay in Review). */
export function deleteConversation(db: AppDb, conversationId: string): void {
  const now = new Date().toISOString();
  db.transaction((tx) => {
    tx.update(schema.conversations)
      .set({ deletedAt: now, updatedAt: now })
      .where(eq(schema.conversations.id, conversationId))
      .run();
    enqueue(tx, "delete_conversation", { id: conversationId });
  });
}

/** Saves an earlier version again as the newest, exactly as it was (no new cleanup). */
export function restoreTakeVersion(db: AppDb, takeId: string, version: number): void {
  const versionId = randomUUID();
  const now = new Date().toISOString();
  db.transaction((tx) => {
    const earlier = tx
      .select()
      .from(schema.takeVersions)
      .where(and(eq(schema.takeVersions.takeId, takeId), eq(schema.takeVersions.version, version)))
      .get();
    if (!earlier) return;
    insertTakeVersion(tx, {
      takeId,
      versionId,
      body: earlier.body ?? earlier.rawBody,
      rawBody: earlier.rawBody,
      cleaned: earlier.cleaned === 1,
      origin: "restore",
      now,
    });
    enqueue(tx, "restore_take_version", { id: takeId, version, version_id: versionId });
  });
}

/** Try again after Clean it up gave up: the page shows "Cleaning up…" until the cleaned version arrives. */
export function retryTakeCleanup(db: AppDb, takeId: string, versionId: string): void {
  db.transaction((tx) => {
    tx.update(schema.takeVersions)
      .set({ body: null, cleanFailed: 0 })
      .where(eq(schema.takeVersions.id, versionId))
      .run();
    enqueue(tx, "retry_take_cleanup", { id: takeId, version_id: versionId });
  });
}
