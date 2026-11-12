import type { ConversationRow } from "./types";

/** The chat a card's page continues: its latest live chat about the card (newest activity first), or null. */
export function latestCardChat(conversations: ConversationRow[], cardId: string): ConversationRow | null {
  return conversations
    .filter((conversation) => conversation.aboutCardId === cardId && conversation.deletedAt === null)
    .reduce<ConversationRow | null>(
      (best, conversation) =>
        best === null || Date.parse(conversation.updatedAt) > Date.parse(best.updatedAt) ? conversation : best,
      null,
    );
}

/**
 * Whether a card page's fallback chat id already names one of the card's chats. A live one would be the page's
 * latest chat, so a match is a deleted chat: reusing its id would show its messages and send into a 404.
 */
export function isFallbackIdTaken(conversations: ConversationRow[], cardId: string, fallbackId: string): boolean {
  return conversations.some((conversation) => conversation.aboutCardId === cardId && conversation.id === fallbackId);
}
