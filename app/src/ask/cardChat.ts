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
