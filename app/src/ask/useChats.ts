import { asc, desc, eq, isNull } from "drizzle-orm";
import { useLiveQuery } from "drizzle-orm/expo-sqlite";
import { useMemo } from "react";

import { db } from "@/db/client";
import * as schema from "@/db/schema";

import type { ConversationRow, MessageRow } from "./types";

export type ChatListItem = { conversation: ConversationRow; lastAnswer: MessageRow | null };

/** Live chats, newest activity first, each with its latest answer. */
export function useChats(): ChatListItem[] {
  const { data: conversations } = useLiveQuery(
    db
      .select()
      .from(schema.conversations)
      .where(isNull(schema.conversations.deletedAt))
      .orderBy(desc(schema.conversations.updatedAt)),
  );
  const { data: answers } = useLiveQuery(
    db
      .select()
      .from(schema.messages)
      .where(eq(schema.messages.role, "assistant"))
      .orderBy(asc(schema.messages.createdAt)),
  );

  return useMemo(() => {
    const latest = new Map(answers.map((answer) => [answer.conversationId, answer]));
    return conversations.map((conversation) => ({ conversation, lastAnswer: latest.get(conversation.id) ?? null }));
  }, [conversations, answers]);
}

/** One chat and its messages, oldest first. */
export function useChat(conversationId: string): {
  conversation: ConversationRow | null;
  messages: MessageRow[];
  // False until the messages have been read from the phone's database.
  loaded: boolean;
} {
  const { data: conversations } = useLiveQuery(
    db.select().from(schema.conversations).where(eq(schema.conversations.id, conversationId)),
    [conversationId],
  );
  const { data: messages, updatedAt: messagesRead } = useLiveQuery(
    db
      .select()
      .from(schema.messages)
      .where(eq(schema.messages.conversationId, conversationId))
      .orderBy(asc(schema.messages.createdAt), asc(schema.messages.id)),
    [conversationId],
  );
  return { conversation: conversations[0] ?? null, messages, loaded: messagesRead !== undefined };
}
