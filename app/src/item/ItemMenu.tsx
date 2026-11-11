import { useRouter } from "expo-router";
import { useState } from "react";

import { openChat } from "@/ask/openChat";
import { deleteSource, goDeeper, queuePrimer, setCardsOff, setRead, setSourceTopic } from "@/db/actions";
import { db } from "@/db/client";
import type * as schema from "@/db/schema";
import { requestSync } from "@/sync/useSync";
import { haptic } from "@/ui/haptics";
import { MenuSheet, type MenuItem } from "@/ui/MenuSheet";
import { SnoozeSheet } from "@/ui/SnoozeSheet";
import { TopicChooserSheet } from "@/ui/TopicChooserSheet";

import { makeCardsAction } from "./cardsMenu";
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
  visible: boolean;
  onClose: () => void;
};
type Panel = "topic" | "snooze" | "episodes" | null;

/**
 * The ••• menu, grouped by how often each is used: [Ask about this] [Remind me later…, Mark as read/unread]
 * [Queue the primer, Make review cards, No cards for this, Change topic, Summary versions, Primer versions, Wrong episode?] [Delete]; and the sheets its entries open.
 */
export function ItemMenu({
  source,
  cardCount,
  primerWords,
  summaryVersions,
  primerVersions,
  onOpenVersions,
  visible,
  onClose,
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
      onPress: () => openChat(router, { kind: "source", id: source.id, title: source.title ?? source.url }),
    },
    ...(!queue.snooze
      ? []
      : [{ testID: "menu-snooze", label: "Remind me later…", startsGroup: true, onPress: () => setPanel("snooze") }]),
    ...(source.kind === "newsletter" && inInbox
      ? [
          {
            testID: "menu-read",
            label: isRead ? "Mark as unread" : "Mark as read",
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
            subtitle: "Removes its cards and makes no more",
            onPress: () => {
              setCardsOff(db, source.id, true);
              haptic("success");
              requestSync();
            },
          },
        ]
      : []),
    { testID: "menu-change-topic", label: "Change topic", onPress: () => setPanel("topic") },
    ...(summaryVersions > 1
      ? [{ testID: "menu-summary-versions", label: "Summary versions", onPress: () => onOpenVersions("summary") }]
      : []),
    ...(primerVersions > 1
      ? [{ testID: "menu-primer-versions", label: "Primer versions", onPress: () => onOpenVersions("primer") }]
      : []),
    ...(source.kind === "podcast"
      ? [{ testID: "menu-episode", label: "Wrong episode?", onPress: () => setPanel("episodes") }]
      : []),
    {
      testID: "menu-delete",
      label: "Delete",
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
      <MenuSheet visible={visible} onClose={onClose} items={items} />
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
