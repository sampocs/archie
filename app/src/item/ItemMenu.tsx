import { useRouter } from "expo-router";
import { useState } from "react";
import { Linking } from "react-native";

import { openChat } from "@/ask/openChat";
import { deleteSource, goDeeper, queuePrimer, setCardsOff, setRead, setSourceTopic } from "@/db/actions";
import { db } from "@/db/client";
import type * as schema from "@/db/schema";
import { requestSync } from "@/sync/useSync";
import { haptic } from "@/ui/haptics";
import { MoreMenu, type MenuItem } from "@/ui/NativeMenu";
import { SnoozeSheet } from "@/ui/SnoozeSheet";
import { TopicChooserSheet } from "@/ui/TopicChooserSheet";

import { makeCardsAction } from "./cardsMenu";
import { originalUrl } from "./originalUrl";
import { EpisodesSheet } from "./EpisodesSheet";
import { queueEntries } from "./menuVisibility";

type SourceRow = typeof schema.sources.$inferSelect;
type ItemMenuProps = {
  source: SourceRow;
  cardCount: number;
  primerWords: number | null;
  summaryVersions: number;
  primerVersions: number;
  onOpenVersions: (kind: "summary" | "primer") => void;
};
type Panel = "topic" | "snooze" | "episodes" | null;

/**
 * The ••• button and its native menu, grouped by how often each is used: [Ask about this] [Remind me later…, Mark as
 * read/unread] [Queue the primer, Make review cards, No cards for this, Change topic, Summary versions, Primer
 * versions, Wrong episode?] [Delete]; and the sheets its picker entries open once the menu has closed.
 */
export function ItemMenu({
  source,
  cardCount,
  primerWords,
  summaryVersions,
  primerVersions,
  onOpenVersions,
}: ItemMenuProps) {
  const router = useRouter();
  const [panel, setPanel] = useState<Panel>(null);
  const inInbox = source.state === "inbox" || source.state === "briefed";
  const isRead = source.readAt !== null;
  const queue = queueEntries(source, primerWords);
  const primerQueued = source.primerQueuePosition !== null;
  const makeCards = makeCardsAction(source, cardCount);

  const items: MenuItem[] = [
    {
      testID: "menu-ask",
      label: "Ask about this",
      icon: "bubble.left.and.text.bubble.right",
      onPress: () => openChat(router, { kind: "source", id: source.id, title: source.title ?? source.url }),
    },
    ...(originalUrl(source.url)
      ? [{ testID: "menu-open-original", label: "Open original", icon: "safari", onPress: () => void Linking.openURL(source.url) }]
      : []),
    ...(!queue.snooze
      ? []
      : [{ testID: "menu-snooze", label: "Remind me later…", icon: "clock", startsGroup: true, onPress: () => setPanel("snooze") }]),
    ...(source.kind === "newsletter" && inInbox
      ? [
          {
            testID: "menu-read",
            label: isRead ? "Mark as unread" : "Mark as read",
            icon: isRead ? "envelope.badge" : "envelope.open",
            onPress: () => {
              setRead(db, source.id, !isRead);
              requestSync();
            },
          },
        ]
      : []),
    ...(!queue.queuePrimer
      ? []
      : [
          {
            testID: "menu-queue-primer",
            label: primerQueued ? "Primer is queued" : "Queue the primer",
            icon: "text.badge.plus",
            subtitle: primerQueued ? undefined : "Adds it to your queue as its own item",
            startsGroup: true,
            onPress: () => {
              queuePrimer(db, source.id, !primerQueued);
              haptic("success");
              requestSync();
            },
          },
        ]),
    ...(makeCards
      ? [
          {
            testID: "menu-review-cards",
            label: "Make review cards",
            icon: "rectangle.stack.badge.plus",
            subtitle: makeCards.subtitle,
            onPress: () => {
              if (makeCards.kind === "go_deeper") goDeeper(db, source.id);
              else setCardsOff(db, source.id, false);
              haptic("success");
              requestSync();
            },
          },
        ]
      : []),
    ...(source.cardsOff === 0
      ? [
          {
            testID: "menu-cards-off",
            label: "No cards for this",
            icon: "rectangle.stack.badge.minus",
            subtitle: "Removes its cards and makes no more",
            onPress: () => {
              setCardsOff(db, source.id, true);
              haptic("success");
              requestSync();
            },
          },
        ]
      : []),
    { testID: "menu-change-topic", label: "Change topic", icon: "tag", onPress: () => setPanel("topic") },
    ...(summaryVersions > 1
      ? [{ testID: "menu-summary-versions", label: "Summary versions", icon: "clock.arrow.circlepath", onPress: () => onOpenVersions("summary") }]
      : []),
    ...(primerVersions > 1
      ? [{ testID: "menu-primer-versions", label: "Primer versions", icon: "clock.arrow.circlepath", onPress: () => onOpenVersions("primer") }]
      : []),
    ...(source.kind === "podcast"
      ? [{ testID: "menu-episode", label: "Wrong episode?", icon: "waveform", onPress: () => setPanel("episodes") }]
      : []),
    {
      testID: "menu-delete",
      label: "Delete",
      icon: "trash",
      destructive: true,
      startsGroup: true,
      onPress: () => {
        deleteSource(db, source.id);
        haptic("success");
        requestSync();
        router.back();
      },
    },
  ];

  return (
    <>
      <MoreMenu testID="item-more" items={items} />
      <TopicChooserSheet
        visible={panel === "topic"}
        onClose={() => setPanel(null)}
        title="Change topic"
        onChoose={(topic) => {
          setSourceTopic(db, source.id, topic.id);
          requestSync();
        }}
      />
      <SnoozeSheet target="source" id={source.id} visible={panel === "snooze"} onClose={() => setPanel(null)} />
      <EpisodesSheet sourceId={source.id} visible={panel === "episodes"} onClose={() => setPanel(null)} />
    </>
  );
}
