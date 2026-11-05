import { integer, real, sqliteTable, text } from "drizzle-orm/sqlite-core";

export const sources = sqliteTable("sources", {
  id: text("id").primaryKey(),
  url: text("url").notNull(),
  title: text("title"),
  kind: text("kind").notNull(),
  state: text("state").notNull(),
  intent: text("intent").notNull(),
  createdAt: text("created_at").notNull(),
  updatedAt: text("updated_at").notNull(),
  deletedAt: text("deleted_at"),
  syncError: text("sync_error"),
  // Server-derived pipeline status (pending, processing, ready, failed, unsupported).
  processing: text("processing").notNull().default("pending"),
  processingError: text("processing_error"),
  reaction: text("reaction"),
  note: text("note"),
  mergedIntoId: text("merged_into_id"),
  // Newsletter sender (display name or address); null for other kinds.
  sender: text("sender"),
  // Filing, artwork and reading state (M4). `queuePosition`: lower is higher in the queue.
  domain: text("domain"),
  topicId: text("topic_id"),
  imageUrl: text("image_url"),
  queuePosition: real("queue_position"),
  readAt: text("read_at"),
  snoozedUntil: text("snoozed_until"),
  primerOpenedAt: text("primer_opened_at"),
  // The source's primer as its own queue entry: same position space as `queuePosition`; null = not queued.
  primerQueuePosition: real("primer_queue_position"),
  primerSnoozedUntil: text("primer_snoozed_until"),
  newsletterKind: text("newsletter_kind"),
});

export const artifacts = sqliteTable("artifacts", {
  id: text("id").primaryKey(),
  sourceId: text("source_id").notNull(),
  kind: text("kind").notNull(),
  version: integer("version").notNull(),
  // JSON-encoded content object.
  content: text("content").notNull(),
  isCurrent: integer("is_current").notNull(),
  createdAt: text("created_at").notNull(),
});

export const cards = sqliteTable("cards", {
  id: text("id").primaryKey(),
  sourceId: text("source_id").notNull(),
  kind: text("kind").notNull(),
  question: text("question").notNull(),
  answer: text("answer").notNull(),
  createdAt: text("created_at").notNull(),
  deletedAt: text("deleted_at"),
});

export const topics = sqliteTable("topics", {
  id: text("id").primaryKey(),
  domain: text("domain").notNull(),
  name: text("name").notNull(),
  // starter | archie | user
  origin: text("origin").notNull(),
  removedAt: text("removed_at"),
  mergedIntoId: text("merged_into_id"),
  createdAt: text("created_at").notNull(),
  updatedAt: text("updated_at").notNull(),
  // Phone only (a pull never writes it): when this phone asked for a primer, so the topic page can say it's coming.
  primerRequestedAt: text("primer_requested_at"),
});

export const topicPrimers = sqliteTable("topic_primers", {
  id: text("id").primaryKey(),
  topicId: text("topic_id").notNull(),
  version: integer("version").notNull(),
  isCurrent: integer("is_current").notNull(),
  // JSON-encoded { markdown }.
  content: text("content").notNull(),
  openedAt: text("opened_at"),
  snoozedUntil: text("snoozed_until"),
  createdAt: text("created_at").notNull(),
});

export const outbox = sqliteTable("outbox", {
  id: text("id").primaryKey(),
  type: text("type").notNull(),
  // JSON-encoded action payload.
  payload: text("payload").notNull(),
  createdAt: text("created_at").notNull(),
  status: text("status", { enum: ["pending", "rejected"] }).notNull(),
  error: text("error"),
});

export const syncState = sqliteTable("sync_state", {
  // Always 1: a single-row table.
  id: integer("id").primaryKey(),
  position: integer("position").notNull(),
  lastPushFailed: integer("last_push_failed").notNull(),
});
