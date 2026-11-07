import type * as schema from "@/db/schema";
import type { PulledCardVersion, PulledEditProposal } from "@/sync/engine";

export type EditTargetKind = "summary" | "primer" | "topic_primer" | "take" | "card";
export type EditStatus = "proposed" | "applied" | "undone" | "discarded" | "stale" | "superseded";
export type VersionOrigin = "archie" | "owner" | "chat_edit" | "care" | "restore";

export type EditProposalRow = typeof schema.editProposals.$inferSelect;
export type CardVersionRow = typeof schema.cardVersions.$inferSelect;

// The `edit` event's data, snake_case as the server sends it.
export type EditProposalWire = {
  id: string;
  target_kind: EditTargetKind;
  target_id: string;
  title: string;
  description: string;
  base_version: number;
  before: unknown;
  after: unknown;
  status: EditStatus;
};

/** What the chat shows of a proposal, the same whether it came from the stream or from the phone's rows. */
export type ProposalView = {
  id: string;
  targetKind: EditTargetKind;
  targetId: string;
  title: string;
  description: string;
  baseVersion: number;
  before: unknown;
  after: unknown;
  status: EditStatus;
  appliedVersion: number | null;
};

const TARGET_KINDS = new Set<string>(["summary", "primer", "topic_primer", "take", "card"]);
const STATUSES = new Set<string>(["proposed", "applied", "undone", "discarded", "stale", "superseded"]);

export function isTargetKind(value: string): value is EditTargetKind {
  return TARGET_KINDS.has(value);
}

/** A stored proposal for the chat; a row of an unknown kind or status (a newer server) reads as null. */
export function viewOfRow(row: EditProposalRow): ProposalView | null {
  if (!isTargetKind(row.targetKind) || !STATUSES.has(row.status)) return null;
  return {
    id: row.id,
    targetKind: row.targetKind,
    targetId: row.targetId,
    title: row.title,
    description: row.description,
    baseVersion: row.baseVersion,
    before: parseJson(row.before),
    after: parseJson(row.after),
    status: row.status as EditStatus,
    appliedVersion: row.appliedVersion,
  };
}

export function viewOfWire(wire: EditProposalWire): ProposalView {
  return {
    id: wire.id,
    targetKind: wire.target_kind,
    targetId: wire.target_id,
    title: wire.title,
    description: wire.description,
    baseVersion: wire.base_version,
    before: wire.before,
    after: wire.after,
    status: wire.status,
    appliedVersion: null,
  };
}

/** The columns of a pulled (or just-returned) proposal, for an upsert. */
export function proposalValues(row: PulledEditProposal): Omit<EditProposalRow, "id"> {
  return {
    conversationId: row.conversation_id,
    messageId: row.message_id,
    targetKind: row.target_kind,
    targetId: row.target_id,
    title: row.title,
    description: row.description,
    baseVersion: row.base_version,
    before: JSON.stringify(row.before),
    after: JSON.stringify(row.after),
    status: row.status,
    appliedVersion: row.applied_version,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

export function cardVersionValues(row: PulledCardVersion): Omit<CardVersionRow, "id"> {
  return {
    cardId: row.card_id,
    version: row.version,
    question: row.question,
    answer: row.answer,
    origin: row.origin,
    instruction: row.instruction,
    createdAt: row.created_at,
  };
}

function parseJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}
