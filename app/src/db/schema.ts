import { integer, sqliteTable, text } from "drizzle-orm/sqlite-core";

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
  prepMe: integer("prep_me").notNull().default(0),
  mergedIntoId: text("merged_into_id"),
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
