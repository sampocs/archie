import { View } from "react-native";

import type { ReviewData } from "@/review/eligibility";
import { cardKicker } from "@/review/kicker";
import type { CardRow } from "@/review/types";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { Kicker } from "@/ui/Kicker";

type QuestionCardProps = { card: CardRow; data: ReviewData };

/** The kicker and the question; the question keeps its size while the keyboard is up. */
export function QuestionCard({ card, data }: QuestionCardProps) {
  const theme = useTheme();
  const kicker = cardKicker(card, data);

  return (
    <View style={{ paddingHorizontal: theme.spacing.gutterText - theme.spacing.gutterCards, gap: theme.spacing.sm }}>
      <Kicker testID="review-kicker" domain={kicker.domain} label={kicker.label} suffix={kicker.suffix} />
      <Text testID="review-question" variant="reviewQuestion">
        {card.question}
      </Text>
    </View>
  );
}
