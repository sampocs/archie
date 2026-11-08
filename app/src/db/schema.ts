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
  // When an article or episode came out; null when unknown and for newsletters (sent and saved the same day).
  publishedAt: text("published_at"),
  // The link a signup-confirmation email asks the owner to open; null for every other source.
  confirmUrl: text("confirm_url"),
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
  // Who made this version: archie, chat_edit or restore (see the versions sheet).
  origin: text("origin").notNull().default("archie"),
  // An Ask edit's one-line description.
  instruction: text("instruction"),
});

export const cards = sqliteTable("cards", {
  id: text("id").primaryKey(),
  // Exactly one origin is set: a source (its summary's cards, or foundation cards from its primer), a topic primer
  // (foundation cards), a brief (quiz cards), a take (take cards) or an Ask chat (chat cards). Later origins add their
  // own column; see review/eligibility.ts.
  sourceId: text("source_id"),
  topicPrimerId: text("topic_primer_id"),
  briefId: text("brief_id"),
  takeId: text("take_id"),
  // Which version of the take the card was written from.
  takeVersionId: text("take_version_id"),
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
  // A card made from an Ask answer: the chat and the answer it came from.
  conversationId: text("conversation_id"),
  messageId: text("message_id"),
  // The current version; card_versions holds the history once the card has changed.
  version: integer("version").notNull().default(1),
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
  origin: text("origin").notNull().default("archie"),
  instruction: text("instruction"),
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

// Collections (Library → Saved): just-for-fun scrapbooks. Their posts live in their own table and are never sources,
// so no library, search, Today or review query can see them.
export const collections = sqliteTable("collections", {
  id: text("id").primaryKey(),
  name: text("name").notNull(),
  // Tile order; a new collection goes at the end.
  position: real("position").notNull(),
  createdAt: text("created_at").notNull(),
  updatedAt: text("updated_at").notNull(),
  deletedAt: text("deleted_at"),
});

export const collectionItems = sqliteTable("collection_items", {
  id: text("id").primaryKey(),
  collectionId: text("collection_id").notNull(),
  url: text("url").notNull(),
  // x | youtube | link; "link" until the server classifies it.
  kind: text("kind").notNull(),
  // The preview the server fetches once: caption or title, who posted it, thumbnail, a video's length.
  title: text("title"),
  author: text("author"),
  imageUrl: text("image_url"),
  durationSeconds: integer("duration_seconds"),
  note: text("note"),
  // pending | ready | failed
  metadataStatus: text("metadata_status").notNull().default("pending"),
  createdAt: text("created_at").notNull(),
  updatedAt: text("updated_at").notNull(),
  deletedAt: text("deleted_at"),
});

// Takes (Library → Takes): what the owner writes. Title and kind live on the take; only the body is versioned.
export const takes = sqliteTable("takes", {
  id: text("id").primaryKey(),
  // opinion | talking_point
  kind: text("kind").notNull(),
  title: text("title").notNull(),
  // The take_versions.version the take page shows.
  currentVersion: integer("current_version").notNull(),
  createdAt: text("created_at").notNull(),
  updatedAt: text("updated_at").notNull(),
  deletedAt: text("deleted_at"),
});

export const takeVersions = sqliteTable("take_versions", {
  id: text("id").primaryKey(),
  takeId: text("take_id").notNull(),
  version: integer("version").notNull(),
  // What the take page shows (markdown); null while Clean it up runs.
  body: text("body"),
  // What the owner typed or dictated.
  rawBody: text("raw_body").notNull(),
  cleaned: integer("cleaned").notNull(),
  // Clean it up gave up: body holds the raw text and the page offers Try again.
  cleanFailed: integer("clean_failed").notNull().default(0),
  createdAt: text("created_at").notNull(),
  // owner for a save in the editor; chat_edit and restore otherwise.
  origin: text("origin").notNull().default("owner"),
});

// Saved Ask chats, written by the server and pulled; the phone only deletes one (an outbox action).
export const conversations = sqliteTable("conversations", {
  id: text("id").primaryKey(),
  title: text("title").notNull(),
  aboutKind: text("about_kind"),
  aboutSourceId: text("about_source_id"),
  aboutTopicPrimerId: text("about_topic_primer_id"),
  aboutTakeId: text("about_take_id"),
  createdAt: text("created_at").notNull(),
  updatedAt: text("updated_at").notNull(),
  deletedAt: text("deleted_at"),
});

export const messages = sqliteTable("messages", {
  id: text("id").primaryKey(),
  conversationId: text("conversation_id").notNull(),
  role: text("role").notNull(),
  text: text("text").notNull(),
  // An answer's segments as JSON (`AnswerSegment[]`); null for a question.
  segments: text("segments"),
  webSearch: integer("web_search").notNull().default(0),
  status: text("status").notNull(),
  createdAt: text("created_at").notNull(),
});

// A card's earlier questions and answers; the server writes versions 1 and 2 on a card's first change.
export const cardVersions = sqliteTable("card_versions", {
  id: text("id").primaryKey(),
  cardId: text("card_id").notNull(),
  version: integer("version").notNull(),
  question: text("question").notNull(),
  answer: text("answer").notNull(),
  origin: text("origin").notNull(),
  instruction: text("instruction"),
  createdAt: text("created_at").notNull(),
});

// Edits Ask proposed in a chat. The phone applies, undoes or discards one through the edit routes, never the outbox.
export const editProposals = sqliteTable("edit_proposals", {
  id: text("id").primaryKey(),
  conversationId: text("conversation_id").notNull(),
  messageId: text("message_id").notNull(),
  targetKind: text("target_kind").notNull(),
  targetId: text("target_id").notNull(),
  title: text("title").notNull(),
  description: text("description").notNull(),
  baseVersion: integer("base_version").notNull(),
  // JSON-encoded content in its edit shape (see edits/content.ts).
  before: text("before").notNull(),
  after: text("after").notNull(),
  status: text("status").notNull(),
  appliedVersion: integer("applied_version"),
  createdAt: text("created_at").notNull(),
  updatedAt: text("updated_at").notNull(),
});
