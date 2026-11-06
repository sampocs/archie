import { Image } from "expo-image";
import { Pressable, StyleSheet, View } from "react-native";

import { mosaicImages, savedCountLabel, type CollectionWithItems } from "@/collections/collections";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";

const MOSAIC_HEIGHT = 92;
const MOSAIC_GAP = 2;

type CollectionTileProps = { collection: CollectionWithItems; onPress: () => void; onLongPress: () => void };

/** One collection in Saved: a 2x2 mosaic of its newest thumbnails over its name and post count. */
export function CollectionTile({ collection, onPress, onLongPress }: CollectionTileProps) {
  const theme = useTheme();
  const images = mosaicImages(collection);

  return (
    <Pressable
      testID={`collection-tile-${collection.id}`}
      onPress={onPress}
      onLongPress={onLongPress}
      style={[
        {
          backgroundColor: theme.colors.surface,
          borderColor: theme.colors.line,
          borderRadius: 16,
          overflow: "hidden",
        },
        styles.card,
        theme.scheme === "light" && styles.shadow,
      ]}
    >
      <View style={{ height: MOSAIC_HEIGHT, gap: MOSAIC_GAP }}>
        {[images.slice(0, 2), images.slice(2, 4)].map((row, rowIndex) => (
          <View key={rowIndex} style={{ flex: 1, flexDirection: "row", gap: MOSAIC_GAP }}>
            {row.map((uri, index) => (
              <View key={index} style={{ flex: 1, backgroundColor: theme.colors.press }}>
                {uri ? <Image source={{ uri }} contentFit="cover" style={StyleSheet.absoluteFill} /> : null}
              </View>
            ))}
          </View>
        ))}
      </View>
      <View style={{ paddingTop: 9, paddingHorizontal: 11, paddingBottom: 11, gap: 2 }}>
        <Text variant="headline" numberOfLines={1}>
          {collection.name}
        </Text>
        <Text variant="monoLabel" tone="ink3" style={{ textTransform: "none" }}>
          {savedCountLabel(collection.items.length)}
        </Text>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: { borderWidth: StyleSheet.hairlineWidth },
  shadow: {
    shadowColor: "#0E0E0C",
    shadowOpacity: 0.06,
    shadowRadius: 2,
    shadowOffset: { width: 0, height: 1 },
  },
});
