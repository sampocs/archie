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
  cardsOff: integer("cards_off").notNull().default(0),
  // When the user starred it; null = not starred. Favorites sort newest star first.
  favoritedAt: text("favorited_at"),
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
  // Exactly one origin is set: a source (its summary's cards, or foundation cards from its primer), a topic primer
  // (foundation cards) or a brief (quiz cards). Later origins add their own column; see review/eligibility.ts.
  sourceId: text("source_id"),
  topicPrimerId: text("topic_primer_id"),
  briefId: text("brief_id"),
  kind: text("kind").notNull(),
  question: text("question").notNull(),
  answer: text("answer").notNull(),
  createdAt: text("created_at").notNull(),
  deletedAt: text("deleted_at"),
  // FSRS state; the phone schedules and the server stores what it last sent.
  fsrsState: text("fsrs_state").notNull().default("new"),
  stability: real("stability"),
  difficulty: real("difficulty"),
  dueAt: text("due_at"),
  lastReviewAt: text("last_review_at"),
  reps: integer("reps").notNull().default(0),
  lapses: integer("lapses").notNull().default(0),
  // Quiz cards only.
  expiresAt: text("expires_at"),
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

// The rolling newsletter brief (M5): the open one and recently finished ones, as the server sends them.
export const briefs = sqliteTable("briefs", {
  id: text("id").primaryKey(),
  // open | done
  status: text("status").notNull(),
  // JSON-encoded { domains, also, essays }; null while the first version is being written.
  content: text("content"),
  // JSON-encoded array of the newsletter ids the content covers.
  sourceIds: text("source_ids").notNull(),
  since: text("since"),
  version: integer("version").notNull(),
  createdAt: text("created_at").notNull(),
  updatedAt: text("updated_at").notNull(),
  doneAt: text("done_at"),
});

// The phone's own review log; reviews are pushed but never pulled. "I actually knew it" reads the replaced
// review's stateBefore from here.
export const reviews = sqliteTable("reviews", {
  id: text("id").primaryKey(),
  cardId: text("card_id").notNull(),
  grade: text("grade").notNull(),
  gradedBy: text("graded_by").notNull(),
  answer: text("answer"),
  missing: text("missing"),
  wasDue: integer("was_due").notNull(),
  reviewedAt: text("reviewed_at").notNull(),
  // JSON-encoded FsrsFields (review/types.ts).
  stateBefore: text("state_before").notNull(),
  stateAfter: text("state_after").notNull(),
  replacesReviewId: text("replaces_review_id"),
});

// Phone only, one row (id 1) once the user changes anything; absent means the defaults.
export const reviewSettings = sqliteTable("review_settings", {
  id: integer("id").primaryKey(),
  reminderEnabled: integer("reminder_enabled").notNull(),
  // Minutes after local midnight.
  reminderMinutes: integer("reminder_minutes").notNull(),
});
