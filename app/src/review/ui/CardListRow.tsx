import { useRouter } from "expo-router";
import { ReactNode } from "react";
import { Pressable, View } from "react-native";

import { dropCard } from "@/db/actions";
import { db } from "@/db/client";
import { SwipeRow } from "@/library/SwipeRow";
import type { CardRow } from "@/review/types";
import { requestSync } from "@/sync/useSync";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { haptic } from "@/ui/haptics";

type CardListRowProps = {
  card: CardRow;
  // The grey line under the question, e.g. "Concept · Due today"; " · Edited" is added for an edited card.
  detail: string;
  index: number;
  // Row, Remove and Versions test ids are `${testIDPrefix}-row-${index}`, `-remove-` and `-versions-`.
  testIDPrefix: string;
  // Offers a Versions swipe action on an edited card.
  onVersions?: () => void;
  end?: ReactNode;
  // The card page's back label (where the row lives, e.g. "Review"); "Back" when absent.
  backLabel?: string;
};

/** One card in a list: its question and detail line; tap opens the card's page, swipe to Remove (or see Versions). */
export function CardListRow({ card, detail, index, testIDPrefix, onVersions, end, backLabel }: CardListRowProps) {
  const theme = useTheme();
  const router = useRouter();
  const edited = card.version > 1;

  return (
    <SwipeRow
      actions={[
        ...(edited && onVersions
          ? [
              {
                key: "versions",
                label: "Versions",
                tone: "neutral" as const,
                testID: `${testIDPrefix}-versions-${index}`,
                onPress: onVersions,
              },
            ]
          : []),
        {
          key: "remove",
          label: "Remove",
          tone: "missed",
          testID: `${testIDPrefix}-remove-${index}`,
          onPress: () => {
            dropCard(db, card.id);
            requestSync();
            haptic("success");
          },
        },
      ]}
    >
      <Pressable
        testID={`${testIDPrefix}-row-${index}`}
        onPress={() => router.push({ pathname: "/card/[id]", params: { id: card.id, from: backLabel } })}
        style={{ flexDirection: "row", alignItems: "center", gap: theme.spacing.md, paddingVertical: theme.spacing.md }}
      >
        <View style={{ flex: 1, gap: theme.spacing.xs }}>
          <Text>{card.question}</Text>
          <Text variant="secondary" tone="ink3">
            {`${detail}${edited ? " · Edited" : ""}`}
          </Text>
        </View>
        {end}
      </Pressable>
    </SwipeRow>
  );
}
