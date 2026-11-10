import { useRouter } from "expo-router";
import { Pressable, View } from "react-native";

import {
  type BrowseMode,
  BROWSE_MODES,
  cardOriginLabel,
  type ItemBrowseRow,
  itemTitle,
  type MissedCard,
  missedTag,
  type TopicBrowseRow,
} from "@/review/browse";
import type { ReviewData } from "@/review/eligibility";
import { cardsWord } from "@/review/labels";
import { cardDueLabel } from "@/review/summary";
import type { CardRow } from "@/review/types";
import { CardListRow } from "@/review/ui/CardListRow";
import { CountTag } from "@/review/ui/CountTag";
import { asTakeKind, TAKE_KIND_DOMAIN, TAKE_KIND_LABELS } from "@/takes/takes";
import { Button } from "@/theme/components/Button";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { slugify } from "@/topics/topicName";
import { GroupedList } from "@/ui/GroupedList";
import { haptic } from "@/ui/haptics";
import { ItemRow } from "@/ui/ItemRow";
import { Kicker } from "@/ui/Kicker";
import { monogramFor } from "@/ui/monogram";
import { CHAT_KIND, colorDomain, kindLabel } from "@/ui/sourceLabels";

const MODE_LABELS: Record<BrowseMode, string> = { topics: "Topics", items: "Items", missed: "Missed" };
const TAKE_MONOGRAM = "❝";

/** The Topics | Items | Missed switch, styled like the Library mode switch. */
export function BrowseModeControl({ mode, onChange }: { mode: BrowseMode; onChange: (mode: BrowseMode) => void }) {
  const theme = useTheme();

  return (
    <View
      style={{ flexDirection: "row", backgroundColor: theme.colors.press, borderRadius: theme.radii.chip, padding: 3 }}
    >
      {BROWSE_MODES.map((option) => (
        <Pressable
          key={option}
          testID={`review-browse-${option}`}
          accessibilityRole="button"
          accessibilityState={{ selected: mode === option }}
          onPress={() => {
            if (option === mode) return;
            haptic("selection");
            onChange(option);
          }}
          style={{
            flex: 1,
            alignItems: "center",
            paddingVertical: theme.spacing.sm,
            borderRadius: theme.radii.chip - 3,
            backgroundColor: mode === option ? theme.colors.surface : "transparent",
          }}
        >
          <Text variant="secondary" tone={mode === option ? "ink" : "ink2"}>
            {MODE_LABELS[option]}
          </Text>
        </Pressable>
      ))}
    </View>
  );
}

/** Topics with reviewable cards: kicker, name, card count, a green due tag; each opens its card list. */
export function TopicsList({ rows }: { rows: TopicBrowseRow[] }) {
  const theme = useTheme();
  const router = useRouter();
  if (rows.length === 0) return <Empty testID="review-topics-empty" line="No topics have cards yet." />;

  return (
    <GroupedList testID="review-topics">
      {rows.map(({ topic, count, due }) => (
        <Pressable
          key={topic.id}
          testID={`review-topic-${slugify(topic.name)}`}
          accessibilityRole="button"
          onPress={() => router.push({ pathname: "/review/cards", params: { topic: topic.id } })}
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: theme.spacing.md,
            paddingVertical: theme.spacing.md,
          }}
        >
          <View style={{ flex: 1, gap: 2 }}>
            <Kicker domain={topic.domain} />
            <Text variant="headline" numberOfLines={2}>
              {topic.name}
            </Text>
            <Text variant="secondary" tone="ink3">
              {cardsWord(count)}
            </Text>
          </View>
          <RowEnd due={due} />
        </Pressable>
      ))}
    </GroupedList>
  );
}

/** Sources and takes with reviewable cards: artwork, title, card count, a green due tag; each opens its card list. */
export function ItemsList({ rows }: { rows: ItemBrowseRow[] }) {
  const router = useRouter();
  if (rows.length === 0) return <Empty testID="review-items-empty" line="No items have cards yet." />;

  return (
    <GroupedList testID="review-items">
      {rows.map((row) => {
        const end = <RowEnd due={row.due} />;
        if (row.kind === "take") {
          const kind = asTakeKind(row.take.kind);
          return (
            <ItemRow
              key={`take-${row.take.id}`}
              testID={`review-item-${row.take.id}`}
              artwork={{ imageUrl: null, domain: TAKE_KIND_DOMAIN[kind], monogram: TAKE_MONOGRAM }}
              kicker={{ domain: TAKE_KIND_DOMAIN[kind], label: TAKE_KIND_LABELS[kind] }}
              title={itemTitle(row)}
              meta={cardsWord(row.count)}
              end={end}
              onPress={() => router.push({ pathname: "/review/cards", params: { take: row.take.id } })}
            />
          );
        }
        const { source } = row;
        return (
          <ItemRow
            key={`source-${source.id}`}
            testID={`review-item-${source.id}`}
            artwork={{
              imageUrl: source.imageUrl,
              domain: colorDomain(source),
              monogram: monogramFor(source),
              circle: source.kind === "x",
            }}
            kicker={{
              domain: colorDomain(source),
              label: source.kind === CHAT_KIND ? kindLabel(source.kind) : undefined,
            }}
            title={itemTitle(row)}
            meta={cardsWord(row.count)}
            end={end}
            onPress={() => router.push({ pathname: "/review/cards", params: { source: source.id } })}
          />
        );
      })}
    </GroupedList>
  );
}

/** Recently missed cards, worst first, each with a red tag, and a button to practice them all. */
export function MissedList({ entries, data, now }: { entries: MissedCard[]; data: ReviewData; now: Date }) {
  const theme = useTheme();
  const router = useRouter();
  if (entries.length === 0) return <Empty testID="review-missed-empty" line="Nothing missed lately." />;

  return (
    <View style={{ gap: theme.spacing.md }}>
      <Button
        testID="review-missed-practice"
        label={`Practice these ${entries.length}`}
        onPress={() => router.push({ pathname: "/review/session", params: { mode: "missed" } })}
      />
      <GroupedList testID="review-missed">
        {entries.map((entry, index) => (
          <CardListRow
            key={entry.card.id}
            card={entry.card}
            detail={`${cardOriginLabel(entry.card, data)} · ${cardDueLabel(entry.card, data, now)}`}
            reviewable
            index={index}
            testIDPrefix="review-missed"
            end={<CountTag label={missedTag(entry)} signal="missed" testID={`review-missed-tag-${index}`} />}
          />
        ))}
      </GroupedList>
    </View>
  );
}

/** Search results as card rows, each saying where it came from. */
export function CardSearchResults({ cards, data, now }: { cards: CardRow[]; data: ReviewData; now: Date }) {
  if (cards.length === 0) return <Empty testID="review-search-empty" line="No cards match." />;

  return (
    <GroupedList testID="review-search-results">
      {cards.map((card, index) => (
        <CardListRow
          key={card.id}
          card={card}
          detail={`${cardOriginLabel(card, data)} · ${cardDueLabel(card, data, now)}`}
          reviewable
          index={index}
          testIDPrefix="review-search"
        />
      ))}
    </GroupedList>
  );
}

function RowEnd({ due }: { due: number }) {
  const theme = useTheme();
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: theme.spacing.sm }}>
      {due > 0 ? <CountTag label={`${due} due`} signal="gotIt" /> : null}
      <Text tone="ink3">›</Text>
    </View>
  );
}

function Empty({ line, testID }: { line: string; testID: string }) {
  return (
    <Text testID={testID} tone="ink2">
      {line}
    </Text>
  );
}
