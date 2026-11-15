import { useRouter } from "expo-router";
import { useState, type ReactNode } from "react";

import { openChat } from "@/ask/openChat";
import { mergeTopic, removeTopic } from "@/db/actions";
import { db } from "@/db/client";
import type { TopicRow } from "@/library/join";
import { requestSync } from "@/sync/useSync";
import { haptic } from "@/ui/haptics";
import type { MenuItem } from "@/ui/NativeMenu";
import { TopicChooserSheet } from "@/ui/TopicChooserSheet";

import { RenameTopicSheet } from "./RenameTopicSheet";

type TopicMenuProps = {
  topic: TopicRow;
  topics: TopicRow[];
  // Given the menu's items, returns whatever opens them: the topic page's ••• button or a chip's long-press.
  children: (items: MenuItem[]) => ReactNode;
  onRemoved?: () => void;
  // Set on the topic page, which follows the merge to the winner instead of showing a dead topic.
  followMerge?: boolean;
  // Set on the topic page when the topic has a current primer: the row starts a chat about it.
  askPrimer?: { id: string; title: string };
  // Set on the topic page when the primer has earlier versions: the row opens the versions sheet.
  onPrimerVersions?: () => void;
};

/**
 * Rename / Merge into… / Remove for a topic, from a chip's long press or the topic page's ••• button; renders the
 * trigger `children` builds from the menu's items, plus the Rename and Merge sheets those items open.
 */
export function TopicMenu({ topic, topics, children, onRemoved, followMerge, askPrimer, onPrimerVersions }: TopicMenuProps) {
  const router = useRouter();
  const [renaming, setRenaming] = useState(false);
  const [merging, setMerging] = useState(false);
  // The Library renders one TopicMenu per chip, so each sheet (a Modal, plus a live query for the chooser) mounts only
  // once it's used; it stays mounted afterwards so the close animation plays.
  const [renameMounted, setRenameMounted] = useState(false);
  const [mergeMounted, setMergeMounted] = useState(false);

  function openRename(): void {
    setRenameMounted(true);
    setRenaming(true);
  }

  function openMerge(): void {
    setMergeMounted(true);
    setMerging(true);
  }

  function merge(target: TopicRow): void {
    mergeTopic(db, topic.id, target.id);
    haptic("success");
    requestSync();
    if (followMerge) router.replace({ pathname: "/topic/[id]", params: { id: target.id } });
  }

  function remove(): void {
    removeTopic(db, topic.id);
    haptic("success");
    requestSync();
    onRemoved?.();
  }

  const items: MenuItem[] = [
    ...(askPrimer
      ? [
          {
            label: "Ask about this",
            testID: "topic-menu-ask",
            icon: "bubble.left.and.text.bubble.right",
            onPress: () => openChat(router, { kind: "topic_primer", id: askPrimer.id, title: askPrimer.title }),
          },
        ]
      : []),
    ...(onPrimerVersions
      ? [{ label: "Primer versions", testID: "topic-menu-primer-versions", icon: "clock.arrow.circlepath", onPress: onPrimerVersions }]
      : []),
    { label: "Rename", testID: "topic-menu-rename", icon: "pencil", onPress: openRename },
    { label: "Merge into…", testID: "topic-menu-merge", icon: "arrow.triangle.merge", onPress: openMerge },
    { label: "Remove", testID: "topic-menu-remove", icon: "trash", destructive: true, onPress: remove },
  ];

  return (
    <>
      {children(items)}
      {renameMounted ? (
        <RenameTopicSheet topic={topic} topics={topics} visible={renaming} onClose={() => setRenaming(false)} />
      ) : null}
      {mergeMounted ? (
        <TopicChooserSheet
          visible={merging}
          onClose={() => setMerging(false)}
          title={`Merge ${topic.name} into…`}
          excludeTopicId={topic.id}
          onChoose={merge}
        />
      ) : null}
    </>
  );
}
