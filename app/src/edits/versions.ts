import type * as schema from "@/db/schema";

import { parseContent, type EditContent } from "./content";
import type { CardVersionRow, VersionOrigin } from "./types";

type ArtifactRow = typeof schema.artifacts.$inferSelect;
type TopicPrimerRow = typeof schema.topicPrimers.$inferSelect;
type TakeVersionRow = typeof schema.takeVersions.$inferSelect;
type CardLike = { question: string; answer: string; detail: string; version: number; createdAt: string };

/** One version as the versions sheet lists it. */
export type VersionEntry = {
  version: number;
  createdAt: string;
  origin: VersionOrigin;
  instruction: string | null;
  content: EditContent | null;
  current: boolean;
};

export const ORIGIN_LABELS: Record<VersionOrigin, string> = {
  archie: "Archie",
  owner: "You",
  chat_edit: "Edited in Ask",
  care: "Rewritten from your note",
  restore: "Restored",
};

export function originLabel(origin: string): string {
  return ORIGIN_LABELS[origin as VersionOrigin] ?? ORIGIN_LABELS.archie;
}

/** One source's summary or primer versions; a summary's content is the `summary` object inside the artifact. */
export function artifactEntries(kind: "summary" | "primer", rows: ArtifactRow[]): VersionEntry[] {
  return newestFirst(
    rows.map((row) => {
      const content = parseJson(row.content) as Record<string, unknown> | null;
      return {
        version: row.version,
        createdAt: row.createdAt,
        origin: asOrigin(row.origin),
        instruction: row.instruction,
        content: parseContent(kind, kind === "summary" ? content?.summary : content),
        current: row.isCurrent === 1,
      };
    }),
  );
}

export function topicPrimerEntries(rows: TopicPrimerRow[]): VersionEntry[] {
  return newestFirst(
    rows.map((row) => ({
      version: row.version,
      createdAt: row.createdAt,
      origin: asOrigin(row.origin),
      instruction: row.instruction,
      content: parseContent("topic_primer", parseJson(row.content)),
      current: row.isCurrent === 1,
    })),
  );
}

/** A take's versions; one still being cleaned shows its raw text, as the take page does. */
export function takeEntries(take: { currentVersion: number }, rows: TakeVersionRow[]): VersionEntry[] {
  return newestFirst(
    rows.map((row) => ({
      version: row.version,
      createdAt: row.createdAt,
      origin: asOrigin(row.origin),
      instruction: null,
      content: { markdown: row.body ?? row.rawBody },
      current: row.version === take.currentVersion,
    })),
  );
}

/** A card's versions; one that never changed has no rows, so it is listed as its single current version. */
export function cardEntries(card: CardLike, rows: CardVersionRow[]): VersionEntry[] {
  if (rows.length === 0) {
    return [
      {
        version: card.version,
        createdAt: card.createdAt,
        origin: "archie",
        instruction: null,
        content: { question: card.question, answer: card.answer, detail: card.detail },
        current: true,
      },
    ];
  }
  return newestFirst(
    rows.map((row) => ({
      version: row.version,
      createdAt: row.createdAt,
      origin: asOrigin(row.origin),
      instruction: row.instruction,
      content: { question: row.question, answer: row.answer, detail: row.detail },
      current: row.version === card.version,
    })),
  );
}

function newestFirst(entries: VersionEntry[]): VersionEntry[] {
  return [...entries].sort((first, second) => second.version - first.version);
}

function asOrigin(origin: string): VersionOrigin {
  return origin in ORIGIN_LABELS ? (origin as VersionOrigin) : "archie";
}

function parseJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}
