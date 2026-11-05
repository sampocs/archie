import { useRouter } from "expo-router";

import { requestPrimer } from "@/db/actions";
import { db } from "@/db/client";
import type * as schema from "@/db/schema";
import { readingMinutes } from "@/library/primer";
import { requestSync } from "@/sync/useSync";
import { Button } from "@/theme/components/Button";
import { useTheme } from "@/theme/useTheme";
import { haptic } from "@/ui/haptics";

type SourceRow = typeof schema.sources.$inferSelect;
type PrimerButtonProps = { source: SourceRow; primerWords: number | null };

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

/** The item's primer as a resource: "◆ Primer · N min" opens it, "✓ Primed" once opened (still tappable). */
export function PrimerButton({ source, primerWords }: PrimerButtonProps) {
  const theme = useTheme();
  const router = useRouter();
  const kind = primerButtonKind(source, primerWords);

  if (kind === "open" && primerWords !== null) {
    const primed = source.primerOpenedAt !== null;
    return (
      <Button
        testID="item-primer"
        variant="secondary"
        label={primed ? "✓ Primed" : `◆ Primer · ${readingMinutes(primerWords)} min`}
        labelColor={primed ? theme.signals.gotIt : undefined}
        onPress={() => router.push({ pathname: "/primer/[id]", params: { id: source.id } })}
      />
    );
  }

  if (kind === "create") {
    return (
      <Button
        testID="item-primer"
        variant="secondary"
        label="Create primer"
        onPress={() => {
          requestPrimer(db, source.id);
          haptic("success");
          requestSync();
        }}
      />
    );
  }
  if (kind === "writing") return <Button testID="item-primer" variant="secondary" label="Writing primer…" disabled />;
  return null;
}
