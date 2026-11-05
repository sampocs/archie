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

/**
 * The item's primer as a resource: "◆ Primer · N min" opens it, "✓ Primed" once opened (still tappable). Without
 * a primer it reads "Writing primer…" (disabled), except a newsletter with nothing running: "Create primer".
 */
export function PrimerButton({ source, primerWords }: PrimerButtonProps) {
  const theme = useTheme();
  const router = useRouter();

  if (primerWords !== null) {
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

  // Newsletters get a primer only on request; anything else is still being written.
  const running = source.processing === "pending" || source.processing === "processing";
  if (source.kind === "newsletter" && !running) {
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
  return <Button testID="item-primer" variant="secondary" label="Writing primer…" disabled />;
}
