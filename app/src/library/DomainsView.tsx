import { useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, View } from "react-native";

import { Card } from "@/theme/components/Card";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { AddTopicSheet } from "@/topics/AddTopicSheet";
import { slugify } from "@/topics/topicName";
import { TopicMenu } from "@/topics/TopicMenu";
import { haptic } from "@/ui/haptics";

import { domainCards, type DomainCard, type DomainChip } from "./domainStats";
import type { LibraryData, TopicRow } from "./join";

type DomainsViewProps = { data: LibraryData };

const UNREAD_DOT = 10;

/** Library's Domains mode: a card per domain with a progress bar and its topic chips, plus "add a topic". */
export function DomainsView({ data }: DomainsViewProps) {
  const theme = useTheme();
  const [adding, setAdding] = useState(false);
  const [menuTopic, setMenuTopic] = useState<TopicRow | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <View testID="domains-view" style={{ gap: theme.spacing.md }}>
      {domainCards(data).map((card) => (
        <DomainCardView key={card.domain} card={card} onChipMenu={(topic) => {
            setMenuTopic(topic);
            setMenuOpen(true);
          }} />
      ))}
      <Pressable testID="add-topic" onPress={() => setAdding(true)} style={{ paddingVertical: theme.spacing.md }}>
        <Text tone="ink2">＋ Add a topic you want to understand</Text>
      </Pressable>
      <AddTopicSheet topics={data.topics} visible={adding} onClose={() => setAdding(false)} />
      {/* The topic stays set after the menu closes so the Rename and Merge sheets it opens keep their topic. */}
      {menuTopic ? (
        <TopicMenu topic={menuTopic} topics={data.topics} visible={menuOpen} onClose={() => setMenuOpen(false)} />
      ) : null}
    </View>
  );
}

function DomainCardView({ card, onChipMenu }: { card: DomainCard; onChipMenu: (topic: TopicRow) => void }) {
  const theme = useTheme();
  const color = theme.domains[card.domain];
  const percent = (part: number): `${number}%` => `${card.count === 0 ? 0 : (part / card.count) * 100}%`;

  return (
    <Card testID={`domain-${slugify(card.domain)}`} style={{ gap: theme.spacing.md }}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: theme.spacing.sm }}>
        <View style={{ width: 10, height: 10, borderRadius: 5, backgroundColor: color }} />
        <Text variant="headline" style={{ flex: 1 }}>
          {card.domain}
        </Text>
        <Text tone="ink3">{card.count}</Text>
      </View>
      <View style={{ flexDirection: "row", height: 6, borderRadius: 3, overflow: "hidden", backgroundColor: theme.colors.press }}>
        <View style={{ width: percent(card.done), backgroundColor: color }} />
        <View style={{ width: percent(card.queued), backgroundColor: color, opacity: 0.6 }} />
        <View style={{ width: percent(card.inbox), backgroundColor: color, opacity: 0.3 }} />
      </View>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: theme.spacing.sm }}>
        {card.chips.map((chip) => (
          <TopicChip key={chip.topic.id} chip={chip} onMenu={() => onChipMenu(chip.topic)} />
        ))}
      </View>
    </Card>
  );
}

function TopicChip({ chip, onMenu }: { chip: DomainChip; onMenu: () => void }) {
  const theme = useTheme();
  const router = useRouter();

  return (
    <Pressable
      testID={`topic-chip-${slugify(chip.topic.name)}`}
      onPress={() => {
        haptic("light");
        router.push({ pathname: "/topic/[id]", params: { id: chip.topic.id } });
      }}
      onLongPress={() => {
        haptic("selection");
        onMenu();
      }}
      style={{
        paddingHorizontal: theme.spacing.md,
        paddingVertical: theme.spacing.sm,
        borderRadius: theme.radii.chip,
        backgroundColor: chip.own ? "transparent" : theme.colors.press,
        borderWidth: chip.own ? 1 : 0,
        borderColor: theme.colors.line,
        flexDirection: "row",
        alignItems: "center",
        gap: theme.spacing.xs,
      }}
    >
      {/* The topic's primer is waiting: the same unread dot artwork uses. */}
      {chip.unreadPrimer ? (
        <View
          testID={`topic-chip-unread-${slugify(chip.topic.name)}`}
          style={{
            width: UNREAD_DOT,
            height: UNREAD_DOT,
            borderRadius: UNREAD_DOT / 2,
            backgroundColor: theme.colors.unread,
          }}
        />
      ) : null}
      <Text variant="secondary">{chip.own ? chip.topic.name : `${chip.topic.name} · ${chip.count}`}</Text>
    </Pressable>
  );
}
