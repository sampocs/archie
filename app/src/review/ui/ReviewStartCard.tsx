import { View } from "react-native";

import { cardsWord } from "@/review/labels";
import { minutesFor } from "@/review/summary";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { CardHeader, ON_GREEN_SOFT } from "@/today/CardHeader";
import { haptic } from "@/ui/haptics";
import { Tappable } from "@/ui/Tappable";

const BAR_HEIGHT = 4;
// The bar's track: white at 28% over the green.
const BAR_TRACK = "rgba(255,255,255,0.28)";

type ReviewStartCardProps = {
  count: number;
  onPress: () => void;
  testID?: string;
  // Today's header detail ("about 4 min", "5 of 12 done"); the Review tab shows no header.
  headerDetail?: string;
  // Today's progress once some of today's cards are reviewed: "N cards left" and a bar of reviewed / total.
  progress?: { reviewed: number; total: number };
  // Today's due cards the daily cap holds back, named under the minutes before any review; 0 shows nothing.
  waiting?: number;
};

/** The green block that opens a due-cards session. */
export function ReviewStartCard({
  count,
  onPress,
  testID = "review-start",
  headerDetail,
  progress,
  waiting = 0,
}: ReviewStartCardProps) {
  const theme = useTheme();
  const minutes = minutesFor(count);

  return (
    <Tappable
      testID={testID}
      accessibilityRole="button"
      onPress={() => {
        haptic("light");
        onPress();
      }}
      style={{
        backgroundColor: theme.signals.reviewCard,
        borderRadius: theme.radii.reviewCard,
        padding: theme.spacing.lg,
        gap: theme.spacing.xs,
      }}
    >
      {headerDetail ? <CardHeader label="Review" detail={headerDetail} onGreen testID={`${testID}-detail`} /> : null}
      <Text testID={`${testID}-count`} variant="articleTitle" style={{ color: "#FFFFFF" }}>
        {progress ? `${cardsWord(count)} left` : cardsWord(count)}
      </Text>
      <Text variant="monoLabel" style={{ color: ON_GREEN_SOFT }}>
        {`about ${minutes} ${minutes === 1 ? "minute" : "minutes"}`}
      </Text>
      {waiting > 0 ? (
        <Text testID={`${testID}-waiting`} variant="monoLabel" style={{ color: ON_GREEN_SOFT }}>
          {`${waiting} more wait for tomorrow`}
        </Text>
      ) : null}
      {progress ? (
        <View
          testID={`${testID}-progress`}
          style={{
            height: BAR_HEIGHT,
            borderRadius: BAR_HEIGHT / 2,
            backgroundColor: BAR_TRACK,
            overflow: "hidden",
            marginTop: theme.spacing.sm,
          }}
        >
          <View
            style={{
              width: `${(100 * progress.reviewed) / progress.total}%`,
              height: "100%",
              borderRadius: BAR_HEIGHT / 2,
              backgroundColor: "#FFFFFF",
            }}
          />
        </View>
      ) : null}
    </Tappable>
  );
}
