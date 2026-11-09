import { useRouter } from "expo-router";
import { Pressable, View } from "react-native";

import type { ReviewData } from "@/review/eligibility";
import { cardKicker, chatItemLine } from "@/review/kicker";
import type { CardRow } from "@/review/types";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { Kicker } from "@/ui/Kicker";

type QuestionCardProps = { card: CardRow; data: ReviewData };

/**
 * The kicker and the question; the question keeps its size while the keyboard is up. A chat item's card shows
 * `From {title} · Chat` instead of the kicker, and tapping it opens the item (its cheat sheet).
 */
export function QuestionCard({ card, data }: QuestionCardProps) {
  const theme = useTheme();
  const router = useRouter();
  const kicker = cardKicker(card, data);
  const fromChat = chatItemLine(card, data);

  return (
    <View style={{ paddingHorizontal: theme.spacing.gutterText - theme.spacing.gutterCards, gap: theme.spacing.sm }}>
      {fromChat ? (
        <Pressable
          testID="review-from-chat"
          hitSlop={8}
          onPress={() => router.push({ pathname: "/source/[id]", params: { id: fromChat.sourceId } })}
        >
          <Text variant="secondary" tone="ink3">
            {"From "}
            <Text variant="secondary" tone="ink2" style={{ textDecorationLine: "underline" }}>
              {fromChat.title}
            </Text>
            {` · ${fromChat.kind}`}
          </Text>
        </Pressable>
      ) : (
        <Kicker testID="review-kicker" domain={kicker.domain} label={kicker.label} suffix={kicker.suffix} />
      )}
      <Text testID="review-question" variant="reviewQuestion">
        {card.question}
      </Text>
    </View>
  );
}
