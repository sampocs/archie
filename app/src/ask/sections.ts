import type { EditProposalWire } from "@/edits/types";

import type { CardSetChoice, CardSetWire } from "./cardSets";
import { ANSWER_LABEL_TEXT, formatClock, type AnswerLabel, type AnswerSegment, type AskEvent, type Citation } from "./types";

/** A labelled run of an answer: consecutive blocks with the same label shown as one section. */
export type Section = { label: AnswerLabel; text: string; citations: Citation[] };

type LiveBlock = { text: string; label: AnswerLabel | null; citations: Citation[] };

/** An answer as it streams in: blocks so far, the tool running now, and how it ended. */
export type LiveAnswer = {
  blocks: LiveBlock[];
  searching: "library" | "web" | null;
  messageId: string | null;
  failed: boolean;
  // Edits Ask proposed so far, and whether it is drafting one now.
  proposals: EditProposalWire[];
  editing: boolean;
  // Card sets Ask proposed so far, and whether it is drafting one now.
  cardSets: CardSetWire[];
  draftingCards: boolean;
};

/** A question sent from this screen, with the answer streaming for it; `sentAt` (ms) starts the thinking clock. */
export type PendingQuestion = {
  userMessageId: string;
  text: string;
  webSearch: boolean;
  sentAt: number;
  // The Keep ticks it carried, for the "Kept 3 of 5 cards" line under it.
  cardSetChoice: CardSetChoice | null;
  live: LiveAnswer;
};

export const EMPTY_LIVE: LiveAnswer = {
  blocks: [],
  searching: null,
  messageId: null,
  failed: false,
  proposals: [],
  editing: false,
  cardSets: [],
  draftingCards: false,
};

// No tool is running: what every event but a tool's start event leaves behind.
const IDLE = { searching: null, editing: false, draftingCards: false } as const;

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DAY_MS = 86_400_000;

/** Sections from an answer's segments: empty text dropped, same-label neighbours joined, each chip once. */
export function groupSections(segments: AnswerSegment[]): Section[] {
  const sections: Section[] = [];
  for (const segment of segments) {
    const text = segment.text.trim();
    if (!text) continue;
    const last = sections.at(-1);
    if (last && last.label === segment.label) {
      last.text = `${last.text} ${text}`;
      last.citations = uniqueCitations([...last.citations, ...segment.citations]);
    } else {
      sections.push({ label: segment.label, text, citations: uniqueCitations(segment.citations) });
    }
  }
  return sections;
}

/** What a citation chip says. */
export function chipText(citation: Citation): string {
  if (citation.kind === "web") return hostOf(citation.url) ?? citation.title;
  if (citation.start_seconds !== null) return `${citation.title} · ${formatClock(citation.start_seconds)}`;
  if (citation.owner_kind === "source_summary") return `${citation.title} · Summary`;
  if (citation.owner_kind === "source_primer" || citation.owner_kind === "topic_primer") {
    return `${citation.title} · Primer`;
  }
  return citation.title;
}

/** One stream event applied to the answer so far. */
export function applyEvent(live: LiveAnswer, event: AskEvent): LiveAnswer {
  switch (event.type) {
    case "delta": {
      const blocks = [...live.blocks];
      const block = blocks[event.block] ?? { text: "", label: null, citations: [] };
      blocks[event.block] = { ...block, text: block.text + event.text };
      return { ...live, blocks, ...IDLE };
    }
    case "block": {
      const blocks = [...live.blocks];
      const block = blocks[event.block] ?? { text: "", label: null, citations: [] };
      blocks[event.block] = { ...block, label: event.label, citations: event.citations };
      return { ...live, blocks };
    }
    case "searching":
      return { ...live, ...IDLE, searching: event.kind };
    case "done":
      return { ...live, messageId: event.message_id, ...IDLE };
    case "error":
      return { ...live, failed: true, ...IDLE };
    case "editing":
      return { ...live, ...IDLE, editing: true };
    case "drafting_cards":
      return { ...live, ...IDLE, draftingCards: true };
    case "edit": {
      const { type: _type, ...wire } = event;
      // A repeated event (a retried read of the stream) replaces the proposal rather than adding it twice. A newer
      // proposal for the same target supersedes the still-proposed older ones, as the server does when it saves it.
      const earlier = live.proposals
        .filter((proposal) => proposal.id !== wire.id)
        .map((proposal) =>
          proposal.status === "proposed" && proposal.target_kind === wire.target_kind && proposal.target_id === wire.target_id
            ? { ...proposal, status: "superseded" as const }
            : proposal,
        );
      return { ...live, editing: false, proposals: [...earlier, wire] };
    }
    case "cards": {
      const { type: _type, ...wire } = event;
      // As for edits: a repeated event replaces its set, and a newer set replaces the chat's still-proposed ones.
      const earlier = live.cardSets
        .filter((cardSet) => cardSet.id !== wire.id)
        .map((cardSet) => (cardSet.status === "proposed" ? { ...cardSet, status: "replaced" } : cardSet));
      return { ...live, draftingCards: false, cardSets: [...earlier, wire] };
    }
  }
}

/** A stream that ended without a `done` or `error` event (the connection closed mid-answer) has failed. */
export function endOfStream(live: LiveAnswer): LiveAnswer {
  if (live.messageId !== null || live.failed) return live;
  return { ...live, failed: true, ...IDLE };
}

/**
 * True once the pulled rows can stand in for the overlay: they hold the question and either its answer, or (for a
 * failed stream) some assistant row after the question. The server commits the question before streaming, so the
 * question alone is not enough.
 */
export function handedOver(
  pending: { userMessageId: string; live: LiveAnswer },
  messages: { id: string; role: string }[],
): boolean {
  const questionIndex = messages.findIndex((message) => message.id === pending.userMessageId);
  if (questionIndex === -1) return false;
  const { messageId, failed } = pending.live;
  if (messageId !== null && messages.some((message) => message.id === messageId)) return true;
  return failed && messages.slice(questionIndex + 1).some((message) => message.role === "assistant");
}

/**
 * What the screen shows of a live answer: finished blocks as sections, the block still streaming as plain text, and
 * the thinking row's label (null hides the row).
 */
export function liveView(live: LiveAnswer): { sections: Section[]; streamingText: string; thinking: string | null } {
  const finished = live.blocks.filter((block): block is LiveBlock & { label: AnswerLabel } => block.label !== null);
  const sections = groupSections(
    finished.map((block) => ({ label: block.label, text: block.text, citations: block.citations })),
  );
  const streamingText = live.blocks
    .filter((block) => block.label === null)
    .map((block) => block.text)
    .join("");
  return { sections, streamingText, thinking: thinkingLabel(live, sections.length > 0 || streamingText.trim() !== "") };
}

const THINKING = "Thinking";
const SEARCHING_TEXT = { library: "Searching your library…", web: "Searching the web…" } as const;

/**
 * The thinking row's label: what the running tool is doing, else "Thinking" until the first text streams; null once
 * text streams with no tool running, and once the answer ended either way.
 */
export function thinkingLabel(live: LiveAnswer, hasText: boolean): string | null {
  if (live.messageId !== null || live.failed) return null;
  if (live.searching) return SEARCHING_TEXT[live.searching];
  if (live.editing) return "Drafting an edit…";
  if (live.draftingCards) return "Drafting cards…";
  return hasText ? null : THINKING;
}

/** "5m", "2h", "Yesterday", "Tue", "Oct 2": a chat row's time. */
export function relativeTime(iso: string, now: Date): string {
  const then = new Date(iso);
  const minutes = Math.floor((now.getTime() - then.getTime()) / 60_000);
  if (minutes < 60) return `${Math.max(1, minutes)}m`;
  if (minutes < 24 * 60 && then.getDate() === now.getDate()) return `${Math.floor(minutes / 60)}h`;

  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const daysAgo = Math.ceil((startOfToday - then.getTime()) / DAY_MS);
  if (daysAgo <= 1) return "Yesterday";
  if (daysAgo < 7) return WEEKDAYS[then.getDay()];
  return `${MONTHS[then.getMonth()]} ${then.getDate()}`;
}

/**
 * A chat row's second line: the last answer's first line, after its label when it came from somewhere ("Your library:
 * …", "Web: …"). Background text has no source to name, so its label would only be noise in a one-line preview.
 */
export function rowPreview(segments: AnswerSegment[]): string {
  const [first] = groupSections(segments);
  if (!first) return "";
  const line = first.text.split("\n")[0];
  return first.label === "background" ? line : `${ANSWER_LABEL_TEXT[first.label]}: ${line}`;
}

function uniqueCitations(citations: Citation[]): Citation[] {
  const seen = new Set<string>();
  return citations.filter((citation) => {
    const key =
      citation.kind === "web"
        ? citation.url
        : `${citation.source_id ?? citation.topic_primer_id ?? citation.take_id}:${citation.start_seconds ?? ""}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function hostOf(url: string): string | null {
  return URL.canParse(url) ? new URL(url).hostname.replace(/^www\./, "") : null;
}
