import { useRouter } from "expo-router";

import { requestPrimer } from "@/db/actions";
import { db } from "@/db/client";
import type * as schema from "@/db/schema";
import { readingMinutes } from "@/library/primer";
import { requestSync } from "@/sync/useSync";
import { Button } from "@/theme/components/Button";
import { useTheme } from "@/theme/useTheme";
import { haptic } from "@/ui/haptics";

import { primerButtonKind } from "./primerButtonKind";

type SourceRow = typeof schema.sources.$inferSelect;
type PrimerButtonProps = { source: SourceRow; primerWords: number | null };

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
