import { Pressable, View } from "react-native";

import { goDeeper, readLater, setPrepMe } from "@/db/actions";
import { db } from "@/db/client";
import type * as schema from "@/db/schema";
import { requestSync } from "@/sync/useSync";
import { Button } from "@/theme/components/Button";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { haptic } from "@/ui/haptics";

type SourceRow = typeof schema.sources.$inferSelect;
type ItemActionsProps = { source: SourceRow; onFinish: () => void };

/** The state-dependent action row: queued items finish or get prepped; inbox items go deeper or wait. */
export function ItemActions({ source, onFinish }: ItemActionsProps) {
  const theme = useTheme();

  if (source.state === "queued") {
    const prepping = source.prepMe === 1;
    return (
      <View style={{ flexDirection: "row", gap: theme.spacing.sm, alignItems: "center" }}>
        <View style={{ flex: 1 }}>
          <Button testID="item-finish" label="I finished it" onPress={onFinish} />
        </View>
        <Pressable
          testID="item-prep"
          onPress={() => {
            setPrepMe(db, source.id, !prepping);
            haptic("selection");
            requestSync();
          }}
          style={{
            backgroundColor: theme.colors.press,
            borderRadius: theme.radii.chip,
            paddingHorizontal: theme.spacing.lg,
            height: theme.spacing.buttonHeight,
            justifyContent: "center",
          }}
        >
          <Text variant="headline">{prepping ? "✓ Prepping" : "Prep me"}</Text>
        </Pressable>
      </View>
    );
  }

  if (source.state === "inbox" || source.state === "briefed") {
    return (
      <View style={{ flexDirection: "row", gap: theme.spacing.sm }}>
        {/* The server rejects go_deeper until the source is ready. */}
        {source.processing === "ready" ? (
          <View style={{ flex: 1 }}>
            <Button
              testID="item-go-deeper"
              label="Go deeper"
              onPress={() => {
                goDeeper(db, source.id);
                haptic("success");
                requestSync();
              }}
            />
          </View>
        ) : null}
        <View style={{ flex: 1 }}>
          <Button
            testID="item-read-later"
            variant="secondary"
            label="Read later"
            onPress={() => {
              readLater(db, source.id);
              haptic("success");
              requestSync();
            }}
          />
        </View>
      </View>
    );
  }

  return null;
}
