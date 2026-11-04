import { ReactNode } from "react";
import { Pressable, View } from "react-native";

import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";

import { ArtworkTile, type ArtworkTileProps } from "./ArtworkTile";
import { haptic } from "./haptics";
import { Kicker } from "./Kicker";

type ItemRowProps = {
  artwork: Omit<ArtworkTileProps, "size" | "testID">;
  kicker: React.ComponentProps<typeof Kicker>;
  title: string;
  meta: string;
  end?: ReactNode;
  onPress?: () => void;
  onLongPress?: () => void;
  testID?: string;
};

const ARTWORK_SIZE = 44;

/** The shared row: artwork, kicker, two-line title, one-line meta and an optional trailing view. */
export function ItemRow({ artwork, kicker, title, meta, end, onPress, onLongPress, testID }: ItemRowProps) {
  const theme = useTheme();

  function press(): void {
    haptic("light");
    onPress?.();
  }

  return (
    <Pressable
      testID={testID}
      onPress={press}
      onLongPress={onLongPress}
      style={{ flexDirection: "row", alignItems: "center", gap: theme.spacing.md, paddingVertical: theme.spacing.md }}
    >
      <ArtworkTile {...artwork} size={ARTWORK_SIZE} testID={testID ? `${testID}-art` : undefined} />
      <View style={{ flex: 1, gap: 2 }}>
        <Kicker {...kicker} />
        <Text variant="headline" numberOfLines={2}>
          {title}
        </Text>
        <Text variant="secondary" tone="ink3" numberOfLines={1}>
          {meta}
        </Text>
      </View>
      {end}
    </Pressable>
  );
}
