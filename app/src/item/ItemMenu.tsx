import { useRouter } from "expo-router";
import { useState } from "react";

import { deleteSource, setRead, setSourceTopic } from "@/db/actions";
import { db } from "@/db/client";
import type * as schema from "@/db/schema";
import { requestSync } from "@/sync/useSync";
import { haptic } from "@/ui/haptics";
import { MenuSheet } from "@/ui/MenuSheet";
import { SnoozeSheet } from "@/ui/SnoozeSheet";
import { TopicChooserSheet } from "@/ui/TopicChooserSheet";

import { EpisodesSheet } from "./EpisodesSheet";

type SourceRow = typeof schema.sources.$inferSelect;
type ItemMenuProps = { source: SourceRow; visible: boolean; onClose: () => void };
type Panel = "topic" | "snooze" | "episodes" | null;

/** The ••• menu and the sheets its entries open. */
export function ItemMenu({ source, visible, onClose }: ItemMenuProps) {
  const router = useRouter();
  const [panel, setPanel] = useState<Panel>(null);
  const canToggleRead = source.kind === "newsletter" && (source.state === "inbox" || source.state === "briefed");
  const isRead = source.readAt !== null;

  const items = [
    { testID: "menu-change-topic", label: "Change topic", onPress: () => setPanel("topic") },
    { testID: "menu-snooze", label: "Snooze", onPress: () => setPanel("snooze") },
    ...(canToggleRead
      ? [
          {
            testID: "menu-read",
            label: isRead ? "Mark unread" : "Mark read",
            onPress: () => {
              setRead(db, source.id, !isRead);
              requestSync();
            },
          },
        ]
      : []),
    ...(source.kind === "podcast"
      ? [{ testID: "menu-episode", label: "Wrong episode?", onPress: () => setPanel("episodes") }]
      : []),
    {
      testID: "menu-delete",
      label: "Delete",
      destructive: true,
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
