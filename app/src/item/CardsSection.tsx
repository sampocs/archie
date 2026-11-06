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

export type CardsOf = { kind: "source"; id: string } | { kind: "take"; id: string };

/**
 * "Cards from this": the source's or take's live cards in session order, each with when it is next due (and, for a
 * source's, its kind). Rows of cards that can't be reviewed yet ("After you finish") aren't pressable; every row swipes
 * to Remove.
 */
export function CardsSection({ of }: { of: CardsOf }) {
  const theme = useTheme();
  const router = useRouter();
  const data = useReviewData();
  const now = useNow();
  const cards = orderCards(
    data.cards.filter((card) => (of.kind === "source" ? card.sourceId === of.id : card.takeId === of.id)),
  );
  if (cards.length === 0) return null;

  const anyReviewable = cards.some((card) => isReviewable(card, data));

  return (
    <GroupedList
      testID="cards-section"
      title={`Cards from this · ${cards.length}`}
      right={
        anyReviewable ? (
          <Pressable
            testID="cards-practice"
            accessibilityRole="button"
            hitSlop={8}
            onPress={() => router.push(`/review/session?mode=${of.kind}&id=${of.id}`)}
          >
            <Text variant="headline">Practice</Text>
          </Pressable>
        ) : null
      }
    >
      {cards.map((card, index) => {
        const reviewable = isReviewable(card, data);
        const due = cardDueLabel(card, data, now);

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
              {/* A take card's kind label ("Take") adds nothing on the take's own page. */}
              <Text variant="secondary" tone="ink3">
                {of.kind === "take" ? due : `${KIND_LABELS[card.kind] ?? card.kind} · ${due}`}
              </Text>
            </Pressable>
          </SwipeRow>
        );
      })}
    </GroupedList>
  );
}
