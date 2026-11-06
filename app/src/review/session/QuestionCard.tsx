import { useEffect, useState } from "react";
import { Keyboard, View } from "react-native";

import type { ReviewData } from "@/review/eligibility";
import { cardKicker } from "@/review/kicker";
import type { CardRow } from "@/review/types";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { Kicker } from "@/ui/Kicker";

type QuestionCardProps = { card: CardRow; data: ReviewData };

/** The kicker and the question, which shrinks while the keyboard is up so the answer box stays in view. */
export function QuestionCard({ card, data }: QuestionCardProps) {
  const theme = useTheme();
  const keyboardUp = useKeyboardUp();
  const kicker = cardKicker(card, data);

  return (
    <View style={{ paddingHorizontal: theme.spacing.gutterText - theme.spacing.gutterCards, gap: theme.spacing.sm }}>
      <Kicker testID="review-kicker" domain={kicker.domain} label={kicker.label} suffix={kicker.suffix} />
      <Text testID="review-question" variant={keyboardUp ? "reviewQuestionCompact" : "reviewQuestion"}>
        {card.question}
      </Text>
    </View>
  );
}

function useKeyboardUp(): boolean {
  const [up, setUp] = useState(Keyboard.isVisible());

  useEffect(() => {
    const show = Keyboard.addListener("keyboardWillShow", () => setUp(true));
    const hide = Keyboard.addListener("keyboardWillHide", () => setUp(false));
    return () => {
      show.remove();
      hide.remove();
    };
  }, []);

  return up;
}
