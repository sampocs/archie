import { eq } from "drizzle-orm";
import { useLiveQuery } from "drizzle-orm/expo-sqlite";
import { randomUUID } from "expo-crypto";
import { useMemo, useState } from "react";

import { db } from "@/db/client";
import * as schema from "@/db/schema";

import { latestCardChat } from "./cardChat";

/**
 * The chat a card's page shows and continues: its latest live chat about the card, or a new chat's id (created by
 * the first question sent). `loaded` is false until the phone's chats have been read, so the page doesn't start a
 * new chat on the render before an existing one shows up.
 */
export function useCardChat(cardId: string): { conversationId: string; loaded: boolean } {
  const [newId] = useState(() => randomUUID());
  const { data, updatedAt } = useLiveQuery(
    db.select().from(schema.conversations).where(eq(schema.conversations.aboutCardId, cardId)),
    [cardId],
  );
  const latest = useMemo(() => latestCardChat(data, cardId), [data, cardId]);
  return { conversationId: latest?.id ?? newId, loaded: updatedAt !== undefined };
}
