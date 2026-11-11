import { View } from "react-native";

import { nextDueLine } from "@/review/summary";
import { Button } from "@/theme/components/Button";
import { Card } from "@/theme/components/Card";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";

type CaughtUpCardProps = {
  // Live reviewable cards; none means the "No cards yet" card.
  cardCount: number;
  next: { at: Date; count: number } | null;
  aheadCount: number;
  // Due cards the daily cap held back today; any means the "Today's cards are done" card.
  waiting: number;
  now: Date;
  onAhead: () => void;
  onMore: () => void;
  onShuffle: () => void;
};

/**
 * The Review tab's top when today's set is empty: when cards come due next, and two ways to start anyway. With cards
 * held back by the daily cap, it offers those instead of reviewing ahead.
 */
export function CaughtUpCard({
  cardCount,
  next,
  aheadCount,
  waiting,
  now,
  onAhead,
  onMore,
  onShuffle,
}: CaughtUpCardProps) {
  const theme = useTheme();
  const style = { borderRadius: theme.radii.reviewCard, gap: theme.spacing.md };

  if (cardCount === 0) {
    return (
      <Card testID="review-caught-up" style={style}>
        <Text variant="headline">No cards yet</Text>
        <Text variant="secondary" tone="ink2">
          Cards from your items and chats show up here.
        </Text>
      </Card>
    );
  }

  const shuffle = (
    <View style={{ flex: 1 }}>
      <Button testID="review-shuffle" label="Shuffle 10" variant="secondary" onPress={onShuffle} />
    </View>
  );

  if (waiting > 0) {
    return (
      <Card testID="review-caught-up" style={style}>
        <View style={{ gap: theme.spacing.xs }}>
          <Text variant="headline">Today's cards are done</Text>
          <Text testID="review-caught-up-waiting" variant="secondary" tone="ink2">
            {`${waiting} more waiting. They'll lead tomorrow's session.`}
          </Text>
        </View>
        <View style={{ flexDirection: "row", gap: theme.spacing.sm }}>
          <View style={{ flex: 1 }}>
            <Button testID="review-more" label={`Keep going · ${waiting}`} variant="secondary" onPress={onMore} />
          </View>
          {shuffle}
        </View>
      </Card>
    );
  }

  return (
    <Card testID="review-caught-up" style={style}>
      <View style={{ gap: theme.spacing.xs }}>
        <Text variant="headline">All caught up</Text>
        {next ? (
          <Text testID="review-caught-up-next" variant="secondary" tone="ink2">
            {nextDueLine(next, now)}
          </Text>
        ) : null}
      </View>
      <View style={{ flexDirection: "row", gap: theme.spacing.sm }}>
        {aheadCount > 0 ? (
          <View style={{ flex: 1 }}>
            <Button
              testID="review-ahead"
              label={`Review ahead · ${aheadCount}`}
              variant="secondary"
              onPress={onAhead}
            />
          </View>
        ) : null}
        {shuffle}
      </View>
    </Card>
  );
}
