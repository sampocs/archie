import { useEffect, useState } from "react";

import { db } from "@/db/client";
import { renameTopic } from "@/db/actions";
import type { TopicRow } from "@/library/join";
import { requestSync } from "@/sync/useSync";
import { Button } from "@/theme/components/Button";
import { Text } from "@/theme/components/Text";
import { TextField } from "@/theme/components/TextField";
import { BottomSheet } from "@/ui/BottomSheet";
import { haptic } from "@/ui/haptics";

import { topicNameError } from "./topicName";

type RenameTopicSheetProps = { topic: TopicRow; topics: TopicRow[]; visible: boolean; onClose: () => void };

/** Rename a topic; the same name rules as adding one apply. */
export function RenameTopicSheet({ topic, topics, visible, onClose }: RenameTopicSheetProps) {
  const [name, setName] = useState(topic.name);
  const error = topicNameError(name, topics, topic.id);

  useEffect(() => {
    if (visible) setName(topic.name);
  }, [visible, topic.name]);

  function save(): void {
    renameTopic(db, topic.id, name);
    haptic("success");
    requestSync();
    onClose();
  }

  return (
    <BottomSheet visible={visible} onClose={onClose} testID="topic-rename-sheet">
      <Text variant="headline">Rename topic</Text>
      <TextField testID="topic-rename-input" value={name} onChangeText={setName} autoFocus />
      {error ? (
        <Text variant="secondary" tone="ink3" testID="topic-rename-error">
          {error}
        </Text>
      ) : null}
      <Button testID="topic-rename-save" label="Save" disabled={error !== null} onPress={save} />
    </BottomSheet>
  );
}
