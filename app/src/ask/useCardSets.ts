import { and, asc, eq, isNull } from "drizzle-orm";
import { useLiveQuery } from "drizzle-orm/expo-sqlite";
import Storage from "expo-sqlite/kv-store";
import { useCallback, useMemo, useState } from "react";

import { db } from "@/db/client";
import * as schema from "@/db/schema";

import { asCardSetMode, viewOfCardSetRow, type CardSetMode, type CardSetView } from "./cardSets";

// Phone-only, so it lives in the key-value store rather than a synced table.
const MODE_KEY = "ask.cardSetMode";

/** The chat's stored card sets, grouped by the answer that proposed them, in the order they were proposed. */
export function useConversationCardSets(conversationId: string): Map<string, CardSetView[]> {
  const { data } = useLiveQuery(
    db
      .select()
      .from(schema.cardSetProposals)
      .where(eq(schema.cardSetProposals.conversationId, conversationId))
      .orderBy(asc(schema.cardSetProposals.createdAt)),
    [conversationId],
  );
  return useMemo(() => {
    const byMessage = new Map<string, CardSetView[]>();
    for (const row of data) {
      const view = viewOfCardSetRow(row);
      if (view) byMessage.set(row.messageId, [...(byMessage.get(row.messageId) ?? []), view]);
    }
    return byMessage;
  }, [data]);
}

/** One card set's stored row, once the phone has it (after a pull, or right after Save / Discard). */
export function useCardSetRow(id: string): CardSetView | null {
  const { data } = useLiveQuery(
    db.select().from(schema.cardSetProposals).where(eq(schema.cardSetProposals.id, id)),
    [id],
  );
  return useMemo(() => (data[0] ? viewOfCardSetRow(data[0]) : null), [data]);
}

/** The Library item this chat saved into, if it has one: its next Save updates that item. */
export function useChatItemId(conversationId: string): string | null {
  const { data } = useLiveQuery(
    db
      .select({ id: schema.sources.id })
      .from(schema.sources)
      .where(and(eq(schema.sources.chatConversationId, conversationId), isNull(schema.sources.deletedAt))),
    [conversationId],
  );
  return data[0]?.id ?? null;
}

/** One card at a time or the full list: the owner's last choice, kept on this phone. */
export function useCardSetMode(): [CardSetMode, (mode: CardSetMode) => void] {
  const [mode, setMode] = useState<CardSetMode>(() => asCardSetMode(Storage.getItemSync(MODE_KEY)));
  const choose = useCallback((next: CardSetMode) => {
    setMode(next);
    Storage.setItemSync(MODE_KEY, next);
  }, []);
  return [mode, choose];
}
