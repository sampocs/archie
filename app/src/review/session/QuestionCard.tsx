import { useEffect, useState } from "react";
import { Keyboard, View } from "react-native";

import { cardDomain, type ReviewData } from "@/review/eligibility";
import { KIND_LABELS } from "@/review/labels";
import type { CardRow } from "@/review/types";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { Kicker } from "@/ui/Kicker";

type QuestionCardProps = { card: CardRow; data: ReviewData };

/** The kicker and the question, which shrinks while the keyboard is up so the answer box stays in view. */
export function QuestionCard({ card, data }: QuestionCardProps) {
  const theme = useTheme();
  const keyboardUp = useKeyboardUp();
  // Quiz cards have no domain: they read "This week · News" in the neutral colour.
  const kicker =
    card.kind === "quiz"
      ? { label: "This week", suffix: "News", domain: null }
      : { label: undefined, suffix: KIND_LABELS[card.kind], domain: cardDomain(card, data) };

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
