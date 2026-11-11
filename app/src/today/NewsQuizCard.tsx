import { Tappable } from "@/ui/Tappable";

import { shortWeekday } from "@/review/summary";
import { Card } from "@/theme/components/Card";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";

import { CardHeader } from "./CardHeader";

type NewsQuizCardProps = { count: number; until: Date; onPress: () => void };

/** Today's card for the week's open news quiz. */
export function NewsQuizCard({ count, until, onPress }: NewsQuizCardProps) {
  const theme = useTheme();
  return (
    <Tappable testID="today-quiz" accessibilityRole="button" onPress={onPress}>
      <Card style={{ gap: theme.spacing.sm }}>
        <CardHeader
          label="News quiz"
          detail={`${count} ${count === 1 ? "question" : "questions"} · until ${shortWeekday(until)}`}
        />
        <Text variant="headline">This week's news quiz</Text>
        <Text variant="secondary" tone="ink2">
          From your briefs
        </Text>
      </Card>
    </Tappable>
  );
}
