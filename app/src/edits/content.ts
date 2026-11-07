import type { EditTargetKind } from "./types";

export type SummaryShape = {
  gist: string;
  key_ideas: { timestamp: string | null; idea: string }[];
  numbers: { timestamp: string | null; fact: string }[];
};
export type MarkdownShape = { markdown: string };
export type CardShape = { question: string; answer: string };
export type EditContent = SummaryShape | MarkdownShape | CardShape;

/** A proposal's or version's content in its kind's shape; anything else (an older or newer shape) is null. */
export function parseContent(kind: EditTargetKind, value: unknown): EditContent | null {
  if (typeof value !== "object" || value === null) return null;
  const record = value as Record<string, unknown>;
  if (kind === "card") {
    return typeof record.question === "string" && typeof record.answer === "string"
      ? { question: record.question, answer: record.answer }
      : null;
  }
  if (kind !== "summary") return typeof record.markdown === "string" ? { markdown: record.markdown } : null;

  const ideas = Array.isArray(record.key_ideas) ? record.key_ideas : null;
  const numbers = Array.isArray(record.numbers) ? record.numbers : null;
  if (typeof record.gist !== "string" || !ideas || !numbers) return null;
  return {
    gist: record.gist,
    key_ideas: ideas
      .filter((item): item is { idea: string; timestamp?: unknown } => typeof item?.idea === "string")
      .map((item) => ({ idea: item.idea, timestamp: typeof item.timestamp === "string" ? item.timestamp : null })),
    numbers: numbers
      .filter((item): item is { fact: string; timestamp?: unknown } => typeof item?.fact === "string")
      .map((item) => ({ fact: item.fact, timestamp: typeof item.timestamp === "string" ? item.timestamp : null })),
  };
}

/** The content as the lines the diff compares: a summary by section, markdown by line, a card as Q and A. */
export function editLines(kind: EditTargetKind, content: EditContent | null): string[] {
  if (content === null) return [];
  if (kind === "card") {
    const card = content as CardShape;
    return [`Question: ${card.question}`, `Answer: ${card.answer}`];
  }
  if (kind !== "summary") {
    return (content as MarkdownShape).markdown
      .split("\n")
      .map((line) => line.trimEnd())
      .filter((line) => line.trim() !== "");
  }

  const summary = content as SummaryShape;
  const lines = ["Gist", summary.gist.trim()];
  if (summary.key_ideas.length > 0) lines.push("Key ideas", ...summary.key_ideas.map((item) => `• ${item.idea}`));
  if (summary.numbers.length > 0) lines.push("Rough numbers", ...summary.numbers.map((item) => `• ${item.fact}`));
  return lines;
}

/** A summary as markdown, for showing an earlier version read-only. */
export function summaryAsMarkdown(summary: SummaryShape): string {
  const parts = [summary.gist.trim()];
  if (summary.key_ideas.length > 0) {
    parts.push("## Key ideas", summary.key_ideas.map((item, index) => `${index + 1}. ${item.idea}`).join("\n"));
  }
  if (summary.numbers.length > 0) {
    parts.push("## Rough numbers", summary.numbers.map((item) => `- ${item.fact}`).join("\n"));
  }
  return parts.join("\n\n");
}
