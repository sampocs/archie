import { useRouter } from "expo-router";
import { Pressable, View } from "react-native";

import type * as schema from "@/db/schema";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { ArtworkTile } from "@/ui/ArtworkTile";
import { Kicker } from "@/ui/Kicker";
import { monogramFor } from "@/ui/monogram";
import { ProcessingLine } from "@/ui/ProcessingLine";
import { kindLabel, sourceByline, stateLabel } from "@/ui/sourceLabels";

type SourceRow = typeof schema.sources.$inferSelect;

export const REACTION_LABELS: Record<string, string> = {
  easy: "Easy",
  mostly: "Mostly followed",
  lost: "Parts lost me",
};

function savedLine(source: SourceRow): string {
  const weekday = new Date(source.createdAt).toLocaleDateString("en-US", { weekday: "long" });
  return `Saved ${weekday} · ${stateLabel(source.state)}`;
}

function Chip({ testID, label, onPress }: { testID: string; label: string; onPress?: () => void }) {
  const theme = useTheme();
  return (
    <Pressable
      testID={testID}
      disabled={!onPress}
      onPress={onPress}
      style={{
        backgroundColor: theme.colors.press,
        borderRadius: theme.radii.chip,
        paddingHorizontal: theme.spacing.md,
        paddingVertical: theme.spacing.xs,
      }}
    >
      <Text variant="secondary">{label}</Text>
    </Pressable>
  );
}

/** Cover, kicker, by-line, saved line and the reaction/topic chips. */
export function ItemHeader({ source, topicName }: { source: SourceRow; topicName: string | null }) {
  const theme = useTheme();
  const router = useRouter();
  const showTopic = source.topicId !== null && topicName !== null;

  return (
    <View style={{ gap: theme.spacing.md }}>
      <View style={{ flexDirection: "row", gap: theme.spacing.md, alignItems: "center" }}>
        <ArtworkTile
          imageUrl={source.imageUrl}
          domain={source.domain}
          monogram={monogramFor(source)}
          size={92}
          circle={source.kind === "x"}
        />
        <View style={{ flex: 1, gap: theme.spacing.xs }}>
          <Kicker domain={source.domain} suffix={kindLabel(source.kind)} />
          <Text variant="secondary" tone="ink2">
            {sourceByline(source)}
          </Text>
          <Text variant="secondary" tone="ink3">
            {savedLine(source)}
          </Text>
        </View>
      </View>
      {source.reaction || showTopic ? (
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: theme.spacing.sm }}>
          {source.reaction ? (
            <Chip testID="item-reaction-chip" label={REACTION_LABELS[source.reaction] ?? source.reaction} />
          ) : null}
          {showTopic ? (
            <Chip testID="item-topic-chip" label={topicName} onPress={() => router.push(`/topic/${source.topicId}`)} />
          ) : null}
        </View>
      ) : null}
      <ProcessingLine source={source} />
    </View>
  );
}
