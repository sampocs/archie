import { eq } from "drizzle-orm";

import { db } from "@/db/client";
import * as schema from "@/db/schema";

import type { ConversationRow } from "./types";

/**
 * The title of the item a chat is about, read from the phone's own tables: a source's title (or its url), a topic
 * primer's topic name, a take's title. Null when the chat is about nothing, or the item isn't on the phone.
 */
export function aboutTitleOf(conversation: ConversationRow | null | undefined): string | null {
  if (!conversation) return null;

  if (conversation.aboutSourceId) {
    const source = db.select().from(schema.sources).where(eq(schema.sources.id, conversation.aboutSourceId)).get();
    return source ? (source.title ?? source.url) : null;
  }

  if (conversation.aboutTopicPrimerId) {
    const primer = db
      .select()
      .from(schema.topicPrimers)
      .where(eq(schema.topicPrimers.id, conversation.aboutTopicPrimerId))
      .get();
    const topic = primer ? db.select().from(schema.topics).where(eq(schema.topics.id, primer.topicId)).get() : null;
    return topic?.name ?? null;
  }

  if (conversation.aboutTakeId) {
    const take = db.select().from(schema.takes).where(eq(schema.takes.id, conversation.aboutTakeId)).get();
    return take?.title ?? null;
  }

  return null;
}
