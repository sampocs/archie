import { useRouter } from "expo-router";
import { Pressable, View } from "react-native";

import { dropCard } from "@/db/actions";
import { db } from "@/db/client";
import { isReviewable } from "@/review/eligibility";
import { KIND_LABELS } from "@/review/labels";
import { orderCards } from "@/review/session";
import { cardDueLabel } from "@/review/summary";
import { useReviewData } from "@/review/useReviewData";
import { SwipeRow } from "@/library/SwipeRow";
import { requestSync } from "@/sync/useSync";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { GroupedList } from "@/ui/GroupedList";
import { haptic } from "@/ui/haptics";
import { useNow } from "@/ui/useNow";

/**
 * "Cards from this": the source's live cards in session order, each with its kind and when it is next due. Rows of
 * cards that can't be reviewed yet ("After you finish") aren't pressable; every row swipes to Remove.
 */
export function CardsSection({ sourceId }: { sourceId: string }) {
  const theme = useTheme();
  const router = useRouter();
  const data = useReviewData();
  const now = useNow();
  const cards = orderCards(data.cards.filter((card) => card.sourceId === sourceId));
  if (cards.length === 0) return null;

  const anyReviewable = cards.some((card) => isReviewable(card, data));

  return (
    <GroupedList
      testID="cards-section"
      title={`Cards from this · ${cards.length}`}
      right={
        anyReviewable ? (
          <Pressable
            testID="cards-practise"
            accessibilityRole="button"
            hitSlop={8}
            onPress={() => router.push(`/review/session?mode=source&id=${sourceId}`)}
          >
            <Text variant="headline">Practise</Text>
          </Pressable>
        ) : null
      }
    >
      {cards.map((card, index) => {
        const reviewable = isReviewable(card, data);

        return (
          <SwipeRow
            key={card.id}
            actions={[
              {
                key: "remove",
                label: "Remove",
                tone: "missed",
                testID: `card-remove-${index}`,
                onPress: () => {
                  dropCard(db, card.id);
                  requestSync();
                  haptic("success");
                },
              },
            ]}
          >
            <Pressable
              testID={`card-row-${index}`}
              disabled={!reviewable}
              onPress={() => router.push(`/review/session?mode=card&id=${card.id}`)}
              style={{ gap: theme.spacing.xs, paddingVertical: theme.spacing.md }}
            >
              <Text>{card.question}</Text>
              <Text variant="secondary" tone="ink3">
                {`${KIND_LABELS[card.kind] ?? card.kind} · ${cardDueLabel(card, data, now)}`}
              </Text>
            </Pressable>
          </SwipeRow>
        );
      })}
    </GroupedList>
  );
}
