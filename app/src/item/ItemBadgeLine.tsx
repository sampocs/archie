import { Pressable, View } from "react-native";

import type * as schema from "@/db/schema";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { itemBadge } from "@/ui/sourceLabels";

type SourceRow = typeof schema.sources.$inferSelect;
// `label` replaces the badge's wording, e.g. a book's "Reading · since Nov 10".
type ItemBadgeLineProps = { source: SourceRow; label?: string; onAddToQueue?: () => void };

/** One line under the title saying where the item is; an inbox item also gets "Add to queue". */
export function ItemBadgeLine({ source, label, onAddToQueue }: ItemBadgeLineProps) {
  const theme = useTheme();
  const badge = itemBadge(source.state);

  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: theme.spacing.sm }}>
      <View
        style={{
          borderWidth: 1,
          borderColor: theme.colors.line,
          borderRadius: theme.radii.chipSmall,
          paddingHorizontal: theme.spacing.sm,
          paddingVertical: 2,
        }}
      >
        <Text testID="item-badge" variant="monoLabel" tone="ink2">
          {label ?? badge}
        </Text>
      </View>
      {/* A briefed newsletter was already in a brief, so only a fresh inbox item is promised the next one. */}
      {source.state === "inbox" ? (
        <Text variant="secondary" tone="ink3" style={{ flex: 1 }}>
          In your next brief
        </Text>
      ) : (
        <View style={{ flex: 1 }} />
      )}
      {badge === "Inbox" && onAddToQueue ? (
        <Pressable testID="item-add-to-queue" onPress={onAddToQueue} hitSlop={8}>
          <Text variant="secondary" style={{ textDecorationLine: "underline" }}>
            Add to queue
          </Text>
        </Pressable>
      ) : null}
    </View>
  );
}
