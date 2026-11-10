import { apiFetch, ClientError } from "@/api/client";
import { db } from "@/db/client";
import * as schema from "@/db/schema";
import type { PulledEditProposal } from "@/sync/engine";

import { proposalValues, type EditTargetKind } from "./types";

export type EditAction = "apply" | "undo" | "discard";

/** Applies, undoes or discards a proposal; the server's answer is stored at once so the card updates before a pull. */
export async function sendEditAction(input: {
  proposalId: string;
  action: EditAction;
  sessionKey: string;
}): Promise<PulledEditProposal> {
  const row = (await apiFetch(`/ask/edits/${input.proposalId}/${input.action}`, {
    method: "POST",
    sessionKey: input.sessionKey,
  })) as PulledEditProposal;
  const values = proposalValues(row);
  db.insert(schema.editProposals)
    .values({ id: row.id, ...values })
    .onConflictDoUpdate({ target: schema.editProposals.id, set: values })
    .run();
  return row;
}

/** Saves an earlier version again as the newest; returns the new current version number. */
export async function restoreVersion(input: {
  targetKind: EditTargetKind;
  targetId: string;
  version: number;
  sessionKey: string;
}): Promise<number> {
  const body = (await apiFetch("/versions/restore", {
    method: "POST",
    sessionKey: input.sessionKey,
    body: { target_kind: input.targetKind, target_id: input.targetId, version: input.version },
  })) as { version: number };
  return Number(body.version);
}

/** A 404: the proposal or item is gone (deleted elsewhere). */
export function isNotFound(error: unknown): boolean {
  return error instanceof ClientError && error.status === 404;
}

/** A 409: the edit or the item changed since the phone last looked. */
export function isConflict(error: unknown): boolean {
  return error instanceof ClientError && error.status === 409;
}
