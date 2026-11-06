import { Image } from "expo-image";
import { Linking, Pressable, StyleSheet, View } from "react-native";

import { Text } from "@/theme/components/Text";
import { fontFamily } from "@/theme/type";
import { useTheme } from "@/theme/useTheme";
import { haptic } from "@/ui/haptics";

import { formatDuration, isVideo, postByline, postSiteName, savedDate, type CollectionItemRow } from "./collections";

type PostCardProps = { item: CollectionItemRow; onLongPress: () => void };

/** One saved post: its picture (or a neutral tile with the site), where it's from, when it was saved, its caption and note. */
export function PostCard({ item, onLongPress }: PostCardProps) {
  const theme = useTheme();
  const isLight = theme.scheme === "light";

  return (
    <Pressable
      testID={`collection-post-${item.id}`}
      onPress={() => {
        haptic("light");
        // Opens in X, YouTube or Safari: nothing plays inside Archie.
        void Linking.openURL(item.url);
      }}
      onLongPress={() => {
        haptic("selection");
        onLongPress();
      }}
      style={[
        styles.card,
        { backgroundColor: theme.colors.surface, borderColor: theme.colors.line },
        isLight && styles.shadow,
      ]}
    >
      <View style={[styles.media, { backgroundColor: theme.colors.press }]}>
        {item.imageUrl ? (
          <Image source={{ uri: item.imageUrl }} contentFit="cover" style={StyleSheet.absoluteFill} />
        ) : (
          <Text variant="headline" tone="ink3">
            {postSiteName(item.url)}
          </Text>
        )}
        {isVideo(item) ? (
          <View style={styles.play}>
            <Text style={styles.playGlyph}>▶</Text>
          </View>
        ) : null}
        {item.durationSeconds !== null ? (
          <View style={styles.duration}>
            <Text style={styles.durationText}>{formatDuration(item.durationSeconds)}</Text>
          </View>
        ) : null}
      </View>
      <View style={styles.body}>
        <View style={styles.metaRow}>
          <Text variant="secondary" tone="ink3" numberOfLines={1} style={styles.byline}>
            {postByline(item)}
          </Text>
          <Text variant="secondary" tone="ink3">
            {savedDate(item.createdAt)}
          </Text>
        </View>
        <Text variant="body">{item.title ?? item.url}</Text>
        {item.note ? (
          <Text variant="secondary" tone="ink2" style={{ fontStyle: "italic" }}>
            {item.note}
          </Text>
        ) : null}
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: { borderRadius: 18, borderWidth: StyleSheet.hairlineWidth, overflow: "hidden" },
  shadow: { shadowColor: "#0E0E0C", shadowOpacity: 0.06, shadowRadius: 2, shadowOffset: { width: 0, height: 1 } },
  media: { aspectRatio: 16 / 9, alignItems: "center", justifyContent: "center", overflow: "hidden" },
  play: {
    width: 46,
    height: 46,
    borderRadius: 23,
    backgroundColor: "rgba(0,0,0,0.45)",
    alignItems: "center",
    justifyContent: "center",
  },
  playGlyph: { color: "#FFFFFF", fontSize: 18 },
  duration: {
    position: "absolute",
    right: 10,
    bottom: 10,
    backgroundColor: "rgba(0,0,0,0.5)",
    borderRadius: 6,
    paddingHorizontal: 6,
    paddingVertical: 2,
  },
  durationText: { color: "#FFFFFF", fontFamily: fontFamily.mono, fontSize: 11 },
  body: { paddingTop: 11, paddingHorizontal: 14, paddingBottom: 13, gap: 6 },
  metaRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", gap: 8 },
  byline: { flexShrink: 1 },
});
