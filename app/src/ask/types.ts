import type * as schema from "@/db/schema";
import type { EditProposalWire } from "@/edits/types";

import type { CardSetWire } from "./cardSets";

/** Where an answer's text came from, read off its citations (never the model's own claim). */
export type AnswerLabel = "library" | "web" | "background";
export type OwnerKind = "source_text" | "source_summary" | "source_primer" | "topic_primer" | "take";
export type AboutKind = "source" | "topic_primer" | "take" | "card";

// Wire shapes stay snake_case: they are stored as the server sent them, in `messages.segments`.
export type LibraryCitation = {
  kind: "library";
  title: string;
  source_id: string | null;
  topic_primer_id: string | null;
  take_id: string | null;
  owner_kind: OwnerKind;
  start_seconds: number | null;
  quote: string | null;
};
export type WebCitation = { kind: "web"; title: string; url: string; quote: string | null };
export type Citation = LibraryCitation | WebCitation;
export type AnswerSegment = { label: AnswerLabel; text: string; citations: Citation[] };

/** One server-sent event of an answer stream. */
export type AskEvent =
  | { type: "delta"; block: number; text: string }
  | { type: "block"; block: number; label: AnswerLabel; citations: Citation[] }
  | { type: "searching"; kind: "library" | "web"; query: string }
  | { type: "done"; message_id: string }
  | { type: "error"; message: string }
  | { type: "editing"; target_kind: string | null }
  | ({ type: "edit" } & EditProposalWire)
  | { type: "drafting_cards" }
  | ({ type: "cards" } & CardSetWire);

export type ConversationRow = typeof schema.conversations.$inferSelect;
export type MessageRow = typeof schema.messages.$inferSelect;

export const ANSWER_LABEL_TEXT: Record<AnswerLabel, string> = {
  library: "Your library",
  background: "Background",
  web: "Web",
};

const LABELS = new Set<string>(["library", "web", "background"]);

/** A stored answer's segments; anything malformed (an older or newer shape) reads as no segments. */
export function parseSegments(json: string | null): AnswerSegment[] {
  if (!json) return [];
  try {
    const parsed: unknown = JSON.parse(json);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (segment): segment is AnswerSegment =>
        typeof segment === "object" &&
        segment !== null &&
        LABELS.has((segment as AnswerSegment).label) &&
        typeof (segment as AnswerSegment).text === "string" &&
        Array.isArray((segment as AnswerSegment).citations),
    );
  } catch {
    return [];
  }
}

/** 1880 → "31:20", 3723 → "1:02:03": how a passage's time is shown. */
export function formatClock(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const secs = String(whole % 60).padStart(2, "0");
  return hours > 0 ? `${hours}:${String(minutes).padStart(2, "0")}:${secs}` : `${minutes}:${secs}`;
}
