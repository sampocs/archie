import { Pressable } from "react-native";

import { shortWeekday } from "@/review/summary";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { GroupedList } from "@/ui/GroupedList";

type KeepGoingProps = { aheadCount: number; aheadBy: Date; onAhead: () => void; onTopic: () => void };

/** Extra-practice options shown once the due cards are done. */
export function KeepGoing({ aheadCount, aheadBy, onAhead, onTopic }: KeepGoingProps) {
  const theme = useTheme();
  const rowStyle = {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingVertical: theme.spacing.md,
  } as const;

  return (
    <GroupedList title="Keep going">
      {aheadCount > 0 ? (
        <Pressable testID="keep-going-ahead" accessibilityRole="button" onPress={onAhead} style={rowStyle}>
          <Text>Review ahead</Text>
          <Text variant="secondary" tone="ink3">{`${aheadCount} due by ${shortWeekday(aheadBy)}`}</Text>
        </Pressable>
      ) : null}
      <Pressable testID="keep-going-topic" accessibilityRole="button" onPress={onTopic} style={rowStyle}>
        <Text>Practise a topic ›</Text>
      </Pressable>
    </GroupedList>
  );
}
