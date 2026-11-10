import type * as schema from "@/db/schema";
import { cardsWord } from "@/review/labels";
import type { PulledCardSetProposal } from "@/sync/engine";

export type CardSetStatus = "proposed" | "saved" | "replaced" | "discarded";
export type ProposedCard = { kind: string; question: string; answer: string };
export type CardSetRow = typeof schema.cardSetProposals.$inferSelect;

// The `cards` event's data is the row as the pull sends it.
export type CardSetWire = PulledCardSetProposal;

/** What the chat shows of a card set, the same whether it came from the stream or from the phone's rows. */
export type CardSetView = {
  id: string;
  title: string;
  cheatSheet: string;
  cards: ProposedCard[];
  status: CardSetStatus;
  savedSourceId: string | null;
  kept: number[] | null;
};

/** One card per page, or every card in a numbered list; the phone remembers the owner's choice. */
export type CardSetMode = "pager" | "list";

/** Whether a saved set's Open should go back: the chat was opened from that same item's page, which is still below it. */
export function opensByGoingBack(fromNote: string | undefined, itemId: string): boolean {
  return fromNote === itemId;
}

/** What "Make cards" under an answer sends: the same as typing it, so Ask makes the set with the whole chat in view. */
export const MAKE_CARDS_MESSAGE = "Make cards";

const STATUSES = new Set<string>(["proposed", "saved", "replaced", "discarded"]);

/** A stored card set for the chat; a row of an unknown status (a newer server) reads as null. */
export function viewOfCardSetRow(row: CardSetRow): CardSetView | null {
  if (!STATUSES.has(row.status)) return null;
  return {
    id: row.id,
    title: row.title,
    cheatSheet: row.cheatSheet,
    cards: parseCards(row.cards),
    status: row.status as CardSetStatus,
    savedSourceId: row.savedSourceId,
    kept: parseKept(row.kept),
  };
}

export function viewOfCardSetWire(wire: CardSetWire): CardSetView {
  return {
    id: wire.id,
    title: wire.title,
    cheatSheet: wire.cheat_sheet,
    cards: wire.cards,
    status: STATUSES.has(wire.status) ? (wire.status as CardSetStatus) : "proposed",
    savedSourceId: wire.saved_source_id,
    kept: wire.kept,
  };
}

/** The columns of a pulled (or just-returned) card set, for an upsert. */
export function cardSetValues(row: PulledCardSetProposal): Omit<CardSetRow, "id"> {
  return {
    conversationId: row.conversation_id,
    messageId: row.message_id,
    title: row.title,
    cheatSheet: row.cheat_sheet,
    cards: JSON.stringify(row.cards),
    status: row.status,
    savedSourceId: row.saved_source_id,
    kept: row.kept === null ? null : JSON.stringify(row.kept),
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

/**
 * The status the block shows. A still-proposed stored set reads as replaced once the live answer holds a newer set
 * (`replacedLive`), as the server marks it when it saves that one; any other stored status wins.
 */
export function shownCardSetStatus(view: Pick<CardSetView, "status">, replacedLive = false): CardSetStatus {
  return view.status === "proposed" && replacedLive ? "replaced" : view.status;
}

/** What a card-set block shows: the whole proposal, a saved set's line and item, or one collapsed line. */
export type CardSetBlock =
  | { kind: "proposed" }
  | { kind: "saved"; line: string; itemId: string | null }
  | { kind: "collapsed"; left: string; right: string };

/** The block for a set as it now stands (see `shownCardSetStatus`). */
export function cardSetBlock(view: CardSetView, replacedLive = false): CardSetBlock {
  switch (shownCardSetStatus(view, replacedLive)) {
    case "proposed":
      return { kind: "proposed" };
    case "saved":
      return { kind: "saved", line: savedLine(view), itemId: view.savedSourceId };
    case "replaced":
      return { kind: "collapsed", left: "Earlier proposal", right: "Replaced" };
    case "discarded": {
      const what = hasCheatSheet(view) ? "Cheat sheet" : "Cards";
      return { kind: "collapsed", left: `${what} · ${view.title}`, right: "Discarded" };
    }
  }
}

/** A note's set has no cheat sheet (the note already has its write-up), so its block shows only the cards. */
export function hasCheatSheet(view: Pick<CardSetView, "cheatSheet">): boolean {
  return view.cheatSheet.trim() !== "";
}

/** The toast after Save: a chat's set goes to Library as an item, a note's set only adds cards to the note. */
export function savedToast(view: Pick<CardSetView, "cheatSheet">): string {
  return hasCheatSheet(view) ? "Saved to Library" : "Added to review";
}

/** Every card starts kept; a new proposal has a new id, so its ticks start over. */
export function allKept(count: number): boolean[] {
  return Array.from({ length: count }, () => true);
}

export function toggleKept(kept: boolean[], index: number): boolean[] {
  return kept.map((value, at) => (at === index ? !value : value));
}

/** The indices Save sends: the kept cards, in order. */
export function keptIndices(kept: boolean[]): number[] {
  return kept.flatMap((value, index) => (value ? [index] : []));
}

/** Each card set's Keep ticks, by set id; the screen holds them so the next question can carry them. */
export type CardSetTicks = Record<string, boolean[]>;

/** A set's ticks as the owner left them; one never touched (or whose cards changed) has every card kept. */
export function ticksOf(ticks: CardSetTicks, view: Pick<CardSetView, "id" | "cards">): boolean[] {
  const stored = ticks[view.id];
  return stored && stored.length === view.cards.length ? stored : allKept(view.cards.length);
}

/**
 * The Keep ticks a question carries (`card_set_choice`, as a question's stored segment holds them): the open set's kept
 * indices out of its card count. The server takes `proposal_id` and `kept`.
 */
export type CardSetChoice = { proposal_id: string; kept: number[]; card_count: number };

/** What the next question carries for the chat's open set: nothing when there is none or every card is still kept. */
export function cardSetChoice(view: Pick<CardSetView, "id"> | null, kept: boolean[]): CardSetChoice | null {
  if (!view || kept.every(Boolean)) return null;
  return { proposal_id: view.id, kept: keptIndices(kept), card_count: kept.length };
}

/** "Kept 3 of 5 cards": the muted line under a question that carried Keep ticks. */
export function choiceLine(choice: Pick<CardSetChoice, "kept" | "card_count">): string {
  return `Kept ${choice.kept.length} of ${cardsWord(choice.card_count)}`;
}

/** The Keep ticks a stored question carried; null for one without them (or anything malformed). */
export function storedChoice(segments: string | null): CardSetChoice | null {
  const parsed = segments === null ? null : parseJson(segments);
  const choice: unknown = Array.isArray(parsed) ? (parsed[0] as { card_set_choice?: unknown } | null)?.card_set_choice : null;
  if (typeof choice !== "object" || choice === null) return null;
  const { proposal_id, kept, card_count } = choice as Record<string, unknown>;
  if (typeof proposal_id !== "string" || typeof card_count !== "number" || !Array.isArray(kept)) return null;
  if (!kept.every((index) => typeof index === "number")) return null;
  return { proposal_id, kept: kept as number[], card_count };
}

/** "Save 4", or "Update 4" when this chat already saved its item (a save then updates that item). */
export function saveLabel(keptCount: number, updating: boolean): string {
  return `${updating ? "Update" : "Save"} ${keptCount}`;
}

/** The pager's next page, held to the first and last card. */
export function stepPage(page: number, delta: number, total: number): number {
  return Math.min(Math.max(page + delta, 0), Math.max(total - 1, 0));
}

/** "‹ 2 / 5 ›" without the arrows. */
export function pageLabel(page: number, total: number): string {
  return `${page + 1} / ${total}`;
}

/** "✓ Saved · 4 cards in review": how many of its cards the saved set kept. */
export function savedLine(view: Pick<CardSetView, "kept" | "cards">): string {
  return `✓ Saved · ${cardsWord(view.kept?.length ?? view.cards.length)} in review`;
}

/** The view mode as stored on the phone; anything else (nothing stored yet) is one card at a time. */
export function asCardSetMode(stored: string | null): CardSetMode {
  return stored === "list" ? "list" : "pager";
}

function parseCards(json: string): ProposedCard[] {
  const parsed = parseJson(json);
  if (!Array.isArray(parsed)) return [];
  return parsed.filter(
    (card): card is ProposedCard =>
      typeof card === "object" &&
      card !== null &&
      typeof (card as ProposedCard).question === "string" &&
      typeof (card as ProposedCard).answer === "string",
  );
}

function parseKept(json: string | null): number[] | null {
  if (json === null) return null;
  const parsed = parseJson(json);
  return Array.isArray(parsed) ? parsed.filter((index): index is number => typeof index === "number") : null;
}

function parseJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}
