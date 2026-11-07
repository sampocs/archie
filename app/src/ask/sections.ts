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
};

export const EMPTY_LIVE: LiveAnswer = { blocks: [], searching: null, messageId: null, failed: false };

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
      return { ...live, blocks, searching: null };
    }
    case "block": {
      const blocks = [...live.blocks];
      const block = blocks[event.block] ?? { text: "", label: null, citations: [] };
      blocks[event.block] = { ...block, label: event.label, citations: event.citations };
      return { ...live, blocks };
    }
    case "searching":
      return { ...live, searching: event.kind };
    case "done":
      return { ...live, messageId: event.message_id, searching: null };
    case "error":
      return { ...live, failed: true, searching: null };
  }
}

/** What the screen shows of a live answer: finished blocks as sections, the block still streaming as plain text. */
export function liveView(live: LiveAnswer): {
  sections: Section[];
  streamingText: string;
  searching: "library" | "web" | null;
} {
  const finished = live.blocks.filter((block): block is LiveBlock & { label: AnswerLabel } => block.label !== null);
  return {
    sections: groupSections(finished.map((block) => ({ label: block.label, text: block.text, citations: block.citations }))),
    streamingText: live.blocks
      .filter((block) => block.label === null)
      .map((block) => block.text)
      .join(""),
    searching: live.searching,
  };
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

/** A chat row's second line: the last answer's first line after its label, e.g. "Background: Apple's…". */
export function rowPreview(segments: AnswerSegment[]): string {
  const [first] = groupSections(segments);
  if (!first) return "";
  return `${ANSWER_LABEL_TEXT[first.label]}: ${first.text.split("\n")[0]}`;
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
