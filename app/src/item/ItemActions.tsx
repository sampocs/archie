import { View } from "react-native";

import type * as schema from "@/db/schema";
import { Button } from "@/theme/components/Button";
import { useTheme } from "@/theme/useTheme";

import { PrimerButton, primerButtonKind } from "./PrimerButton";

type SourceRow = typeof schema.sources.$inferSelect;
type ItemActionsProps = { source: SourceRow; primerWords: number | null; onFinish: () => void };

/**
 * At most one primary and one secondary button: queued items are marked done beside the primer button; done items
 * keep the primer button alone; inbox items have none (the badge line's link queues them).
 */
export function ItemActions({ source, primerWords, onFinish }: ItemActionsProps) {
  const theme = useTheme();

  const hasPrimerButton = primerButtonKind(source, primerWords) !== null;

  if (source.state === "queued") {
    return (
      <View style={{ flexDirection: "row", gap: theme.spacing.sm }}>
        <View style={{ flex: 1 }}>
          <Button testID="item-finish" label="Mark as done" onPress={onFinish} />
        </View>
        {hasPrimerButton ? (
          <View style={{ flex: 1 }}>
            <PrimerButton source={source} primerWords={primerWords} />
          </View>
        ) : null}
      </View>
    );
  }
  if (source.state === "consumed") return <PrimerButton source={source} primerWords={primerWords} />;
  return null;
}
