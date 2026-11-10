import { Pressable, View } from "react-native";

import { DAILY_NOTES, type TodayRefresher } from "./refresher";
import { Card } from "@/theme/components/Card";
import { CardHeader } from "@/today/CardHeader";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { ArtworkTile } from "@/ui/ArtworkTile";
import { monogramFor } from "@/ui/monogram";
import { asDomain } from "@/topics/domains";

type RefresherCardProps = {
  state: Extract<TodayRefresher, { kind: "pick" }>;
  onOpen: (id: string) => void;
  onSkip: (id: string) => void;
};

/** Today's "Refresh a note" card: the note to read now and what's next. Once today's are done, Today shows a done row. */
export function RefresherCard({ state, onOpen, onSkip }: RefresherCardProps) {
  const theme = useTheme();
  const { note } = state;

  return (
    <Card testID="today-refresher" style={{ gap: theme.spacing.md }}>
      <CardHeader label="Refresh a note" detail={`${state.position} of ${DAILY_NOTES} today`} testID="today-refresher-detail" />
      <Pressable
        testID="today-refresher-note"
        onPress={() => onOpen(note.id)}
        style={{ flexDirection: "row", alignItems: "center", gap: theme.spacing.md }}
      >
        <ArtworkTile imageUrl={null} domain={note.domain} monogram={monogramFor(note)} size={44} />
        <View style={{ flex: 1, gap: theme.spacing.xs }}>
          <Text variant="headline">{note.title ?? note.url}</Text>
          <Text variant="secondary" tone="ink2">
            {`Notes · ${asDomain(note.domain)} · ${state.minutes} min read`}
          </Text>
        </View>
        <Text tone="ink3">›</Text>
      </Pressable>
      {state.nextUp.length > 0 ? (
        <Text variant="secondary" tone="ink3">{`Next up: ${state.nextUp.join(", ")}`}</Text>
      ) : null}
      <Pressable testID="refresher-skip" onPress={() => onSkip(note.id)} hitSlop={8} style={{ alignSelf: "flex-end" }}>
        <Text variant="secondary" tone="ink2">
          Skip
        </Text>
      </Pressable>
    </Card>
  );
}
