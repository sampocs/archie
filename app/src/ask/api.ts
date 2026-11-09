import { apiFetch } from "@/api/client";
import { db } from "@/db/client";
import * as schema from "@/db/schema";
import type { PulledCardSetProposal } from "@/sync/engine";

import { cardSetValues } from "./cardSets";

/**
 * Saves a proposed card set with the cards the owner kept (indices into its cards), into the chat's Library item. The
 * server's answer is stored at once so the block shows Saved before a pull; the item and its cards arrive with the
 * pull the caller requests.
 */
export async function saveCardSet(input: {
  proposalId: string;
  kept: number[];
  sessionKey: string;
}): Promise<PulledCardSetProposal> {
  return storeAnswer(
    await apiFetch(`/ask/card-sets/${input.proposalId}/save`, {
      method: "POST",
      sessionKey: input.sessionKey,
      body: { kept: input.kept },
    }),
  );
}

/** Discards a proposed card set; stored at once, as for Save. */
export async function discardCardSet(input: { proposalId: string; sessionKey: string }): Promise<PulledCardSetProposal> {
  return storeAnswer(
    await apiFetch(`/ask/card-sets/${input.proposalId}/discard`, { method: "POST", sessionKey: input.sessionKey }),
  );
}

function storeAnswer(body: unknown): PulledCardSetProposal {
  const row = body as PulledCardSetProposal;
  const values = cardSetValues(row);
  db.insert(schema.cardSetProposals)
    .values({ id: row.id, ...values })
    .onConflictDoUpdate({ target: schema.cardSetProposals.id, set: values })
    .run();
  return row;
}
