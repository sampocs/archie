import { useRouter } from "expo-router";
import { useState } from "react";

import { openChat } from "@/ask/openChat";
import { mergeTopic, removeTopic } from "@/db/actions";
import { db } from "@/db/client";
import type { TopicRow } from "@/library/join";
import { requestSync } from "@/sync/useSync";
import { haptic } from "@/ui/haptics";
import { MenuSheet } from "@/ui/MenuSheet";
import { TopicChooserSheet } from "@/ui/TopicChooserSheet";

import { RenameTopicSheet } from "./RenameTopicSheet";

type TopicMenuProps = {
  topic: TopicRow;
  topics: TopicRow[];
  visible: boolean;
  onClose: () => void;
  onRemoved?: () => void;
  // Set on the topic page, which follows the merge to the winner instead of showing a dead topic.
  followMerge?: boolean;
  // Set on the topic page when the topic has a current primer: the row starts a chat about it.
  askPrimer?: { id: string; title: string };
};

/** Rename / Merge into… / Remove for a topic, from a chip's long press or the topic page's ••• button. */
export function TopicMenu({ topic, topics, visible, onClose, onRemoved, followMerge, askPrimer }: TopicMenuProps) {
  const router = useRouter();
  const [renaming, setRenaming] = useState(false);
  const [merging, setMerging] = useState(false);

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

  return (
    <>
      <MenuSheet
        visible={visible}
        onClose={onClose}
        items={[
          ...(askPrimer
            ? [
                {
                  label: "Ask about this",
                  testID: "topic-menu-ask",
                  onPress: () => openChat(router, { kind: "topic_primer", id: askPrimer.id, title: askPrimer.title }),
                },
              ]
            : []),
          { label: "Rename", testID: "topic-menu-rename", onPress: () => setRenaming(true) },
          { label: "Merge into…", testID: "topic-menu-merge", onPress: () => setMerging(true) },
          { label: "Remove", testID: "topic-menu-remove", destructive: true, onPress: remove },
        ]}
      />
      <RenameTopicSheet topic={topic} topics={topics} visible={renaming} onClose={() => setRenaming(false)} />
      <TopicChooserSheet
        visible={merging}
        onClose={() => setMerging(false)}
        title={`Merge ${topic.name} into…`}
        excludeTopicId={topic.id}
        onChoose={merge}
      />
    </>
  );
}
