import { useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { Pressable, View } from "react-native";

import { VersionsSheet } from "@/edits/VersionsSheet";
import { isReviewable } from "@/review/eligibility";
import { KIND_LABELS } from "@/review/labels";
import { orderCards } from "@/review/session";
import { cardDueLabel } from "@/review/summary";
import { CardListRow } from "@/review/ui/CardListRow";
import { useReviewData } from "@/review/useReviewData";
import { Text } from "@/theme/components/Text";
import { GroupedList } from "@/ui/GroupedList";
import { Toast } from "@/ui/Toast";
import { useNow } from "@/ui/useNow";

export type CardsOf = { kind: "source"; id: string } | { kind: "take"; id: string };

/**
 * "Cards from this": the source's or take's live cards in session order, each with when it is next due (and, for a
 * source's, its kind). Rows of cards that can't be reviewed yet ("After you finish") aren't pressable; every row swipes
 * to Remove.
 */
export function CardsSection({ of }: { of: CardsOf }) {
  const router = useRouter();
  const data = useReviewData();
  const now = useNow();
  const [versionsOf, setVersionsOf] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const hideToast = useCallback(() => setToast(null), []);
  const cards = orderCards(
    data.cards.filter((card) => (of.kind === "source" ? card.sourceId === of.id : card.takeId === of.id)),
  );
  if (cards.length === 0) return null;

  const anyReviewable = cards.some((card) => isReviewable(card, data));

  return (
    <>
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
          <CardListRow
            key={card.id}
            card={card}
            // A take card's kind label ("Take") adds nothing on the take's own page.
            detail={of.kind === "take" ? due : `${KIND_LABELS[card.kind] ?? card.kind} · ${due}`}
            reviewable={reviewable}
            index={index}
            testIDPrefix="card"
            onVersions={() => setVersionsOf(card.id)}
          />
        );
      })}
    </GroupedList>
    <VersionsSheet
      target={versionsOf ? { kind: "card", id: versionsOf } : null}
      visible={versionsOf !== null}
      onClose={() => setVersionsOf(null)}
      onRestored={(version) => setToast(`Restored version ${version}`)}
    />
    {toast ? <Toast message={toast} onHide={hideToast} /> : null}
    </>
  );
}
