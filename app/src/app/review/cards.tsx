import { useLocalSearchParams, useRouter } from "expo-router";
import { View } from "react-native";

import { type CardListTarget, cardListOf, cardListTargetOf, cardOriginLabel } from "@/review/browse";
import type { ReviewData } from "@/review/eligibility";
import { KIND_LABELS } from "@/review/labels";
import { orderCards } from "@/review/session";
import { cardDueLabel } from "@/review/summary";
import type { CardRow } from "@/review/types";
import { CardListRow } from "@/review/ui/CardListRow";
import { useReviewData } from "@/review/useReviewData";
import { Button } from "@/theme/components/Button";
import { Screen } from "@/theme/components/Screen";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { GroupedList } from "@/ui/GroupedList";
import { useNow } from "@/ui/useNow";

/**
 * A topic's or item's reviewable cards (`?topic=`, `?source=` or `?take=`), in session order, with Practice all. Each
 * row opens the card's page; swipe to Remove.
 */
export default function CardListScreen() {
  const theme = useTheme();
  const router = useRouter();
  const now = useNow();
  const data = useReviewData();
  const target = cardListTargetOf(useLocalSearchParams<{ topic?: string; source?: string; take?: string }>());
  const list = target ? cardListOf(data, target) : null;
  const cards = list ? orderCards(list.cards) : [];

  return (
    <Screen title={list?.title ?? "Cards"} onBack={router.back}>
      {target === null || cards.length === 0 ? (
        <Text testID="card-list-empty" tone="ink2">
          No cards to practice here.
        </Text>
      ) : (
        <View style={{ gap: theme.spacing.md }}>
          <Button
            testID="card-list-practice"
            label={`Practice all ${cards.length}`}
            onPress={() => router.push({ pathname: "/review/session", params: { mode: target.kind, id: target.id } })}
          />
          <GroupedList testID="card-list">
            {cards.map((card, index) => (
              <CardListRow
                key={card.id}
                card={card}
                detail={`${originOf(card, target, data)}${cardDueLabel(card, data, now)}`}
                index={index}
                testIDPrefix="card-list"
                backLabel="Review"
              />
            ))}
          </GroupedList>
        </View>
      )}
    </Screen>
  );
}

// A topic's list mixes items, so each card says where it came from; an item's own list names the kind, as the item
// page does (nothing for a take's cards, whose kind is always "Take").
function originOf(card: CardRow, target: CardListTarget, data: ReviewData): string {
  if (target.kind === "topic") return `${cardOriginLabel(card, data)} · `;
  if (target.kind === "take") return "";
  return `${KIND_LABELS[card.kind] ?? card.kind} · `;
}
