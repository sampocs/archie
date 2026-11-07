import { asc, eq } from "drizzle-orm";
import { useLiveQuery } from "drizzle-orm/expo-sqlite";
import { useMemo } from "react";

import { db } from "@/db/client";
import * as schema from "@/db/schema";

import { viewOfRow, type ProposalView } from "./types";

/** The chat's stored proposals, grouped by the answer that made them, in the order they were made. */
export function useConversationProposals(conversationId: string): Map<string, ProposalView[]> {
  const { data } = useLiveQuery(
    db
      .select()
      .from(schema.editProposals)
      .where(eq(schema.editProposals.conversationId, conversationId))
      .orderBy(asc(schema.editProposals.createdAt)),
    [conversationId],
  );
  return useMemo(() => {
    const byMessage = new Map<string, ProposalView[]>();
    for (const row of data) {
      const view = viewOfRow(row);
      if (view) byMessage.set(row.messageId, [...(byMessage.get(row.messageId) ?? []), view]);
    }
    return byMessage;
  }, [data]);
}

/** One proposal's stored row, once the phone has it (after a pull, or right after Apply / Undo / Discard). */
export function useProposalRow(id: string): ProposalView | null {
  const { data } = useLiveQuery(db.select().from(schema.editProposals).where(eq(schema.editProposals.id, id)), [id]);
  return useMemo(() => (data[0] ? viewOfRow(data[0]) : null), [data]);
}
