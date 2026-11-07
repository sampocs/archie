import { takeDate } from "@/takes/takes";

import type { EditTargetKind } from "./types";
import { originLabel, type VersionEntry } from "./versions";

const SHEET_TITLES: Record<EditTargetKind, string> = {
  summary: "Summary versions",
  primer: "Primer versions",
  topic_primer: "Primer versions",
  card: "Card versions",
  take: "Earlier versions",
};

export function sheetTitle(kind: EditTargetKind): string {
  return SHEET_TITLES[kind];
}

/** "Version 3 · Nov 8". */
export function versionRowTitle(entry: Pick<VersionEntry, "version" | "createdAt">, now: Date): string {
  return `Version ${entry.version} · ${takeDate(entry.createdAt, now)}`;
}

/** How the version was made, then the edit's description or the care note: "Edited in Ask · Drop the jargon". */
export function versionRowDetail(entry: Pick<VersionEntry, "origin" | "instruction">): string {
  const label = originLabel(entry.origin);
  return entry.instruction ? `${label} · ${entry.instruction}` : label;
}
