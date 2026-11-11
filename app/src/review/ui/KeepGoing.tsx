import { Tappable } from "@/ui/Tappable";

import { shortWeekday } from "@/review/summary";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { GroupedList } from "@/ui/GroupedList";

type KeepGoingProps = {
  // Due cards the daily cap held back, and how long a session of the next batch takes.
  waiting: number;
  moreMinutes: number;
  onMore: () => void;
  aheadCount: number;
  aheadBy: Date;
  onAhead: () => void;
  onTopic: () => void;
};

/** Extra-practice options shown once the due cards are done. */
export function KeepGoing({ waiting, moreMinutes, onMore, aheadCount, aheadBy, onAhead, onTopic }: KeepGoingProps) {
  const theme = useTheme();
  const rowStyle = {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingVertical: theme.spacing.md,
  } as const;

  return (
    <GroupedList title="Keep going">
      {waiting > 0 ? (
        <Tappable testID="keep-going-more" accessibilityRole="button" onPress={onMore} style={rowStyle}>
          <Text>{`${waiting} more waiting`}</Text>
          <Text variant="secondary" tone="ink3">{`about ${moreMinutes} min ›`}</Text>
        </Tappable>
      ) : null}
      {aheadCount > 0 ? (
        <Tappable testID="keep-going-ahead" accessibilityRole="button" onPress={onAhead} style={rowStyle}>
          <Text>Review ahead</Text>
          <Text variant="secondary" tone="ink3">{`${aheadCount} due by ${shortWeekday(aheadBy)}`}</Text>
        </Tappable>
      ) : null}
      <Tappable testID="keep-going-topic" accessibilityRole="button" onPress={onTopic} style={rowStyle}>
        <Text>Practice a topic ›</Text>
      </Tappable>
    </GroupedList>
  );
}
