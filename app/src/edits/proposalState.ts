import type { EditStatus, EditTargetKind, ProposalView } from "./types";

export const KICKERS: Record<EditTargetKind, string> = {
  summary: "Edit · Summary",
  primer: "Edit · Primer",
  topic_primer: "Edit · Topic primer",
  take: "Edit · Take",
  card: "Edit · Card",
};

export const STATUS_LINES: Record<Exclude<EditStatus, "proposed">, string> = {
  applied: "Applied",
  undone: "Undone",
  discarded: "Discarded",
  stale: "Changed since you asked. Ask again to redo it.",
  superseded: "Replaced by a newer suggestion",
};

export const NETWORK_FAILED = "Couldn't reach Archie. Try again.";
export const UNDO_CONFLICT = "This was changed since. Use Earlier versions to go back.";

/**
 * The status the card shows. A proposal whose target this phone already holds at a newer version can't apply, so it
 * reads as stale before Apply is tapped; while the target hasn't loaded (null) it stays as the server said. Versions
 * only grow, so a copy behind the base version is a pull still on its way, not a reason to call it stale.
 */
export function shownStatus(proposal: Pick<ProposalView, "status" | "baseVersion">, currentVersion: number | null): EditStatus {
  if (proposal.status !== "proposed" || currentVersion === null) return proposal.status;
  return currentVersion > proposal.baseVersion ? "stale" : "proposed";
}

/** Where tapping a proposal's title goes: the item's own page, or the card in Review. */
export function targetHref(kind: EditTargetKind, id: string): string {
  switch (kind) {
    case "summary":
      return `/source/${id}`;
    case "primer":
      return `/primer/${id}`;
    case "topic_primer":
      return `/topic/${id}`;
    case "take":
      return `/take/${id}`;
    case "card":
      return `/review/session?mode=card&id=${id}`;
  }
}
