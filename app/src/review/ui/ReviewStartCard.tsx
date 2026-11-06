import { Pressable, View } from "react-native";

import { cardsWord } from "@/review/labels";
import { minutesFor } from "@/review/summary";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { haptic } from "@/ui/haptics";

type ReviewStartCardProps = { count: number; foundations: number; onPress: () => void; testID?: string };

/** The green block that opens a due-cards session. */
export function ReviewStartCard({ count, foundations, onPress, testID = "review-start" }: ReviewStartCardProps) {
  const theme = useTheme();
  const minutes = minutesFor(count);

  return (
    <Pressable
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
      <Text testID={`${testID}-count`} variant="articleTitle" style={{ color: "#FFFFFF" }}>
        {cardsWord(count)}
      </Text>
      <View style={{ gap: theme.spacing.xs }}>
        <Text variant="monoLabel" style={{ color: "#FFFFFF" }}>
          {`about ${minutes} ${minutes === 1 ? "minute" : "minutes"}`}
        </Text>
        {foundations > 0 ? (
          <Text variant="secondary" style={{ color: "#FFFFFF" }}>
            {`${foundations} ${foundations === 1 ? "foundation" : "foundations"} first`}
          </Text>
        ) : null}
      </View>
    </Pressable>
  );
}
