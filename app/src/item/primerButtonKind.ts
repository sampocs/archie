import type * as schema from "@/db/schema";

type SourceRow = typeof schema.sources.$inferSelect;

export type PrimerButtonKind = "open" | "create" | "writing" | null;

/**
 * Which primer button an item shows: its primer when there is one; "Create primer" for a ready newsletter (they get
 * one only on request); "Writing primer…" while the pipeline runs; none when it failed (the page offers Retry).
 */
export function primerButtonKind(
  source: Pick<SourceRow, "kind" | "processing">,
  primerWords: number | null,
): PrimerButtonKind {
  if (primerWords !== null) return "open";
  if (source.processing === "pending" || source.processing === "processing") return "writing";
  if (source.kind === "newsletter" && source.processing === "ready") return "create";
  return null;
}
