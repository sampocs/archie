import { useLiveQuery } from "drizzle-orm/expo-sqlite";
import { useMemo, useState } from "react";
import { Pressable, ScrollView, View } from "react-native";

import { db } from "@/db/client";
import * as schema from "@/db/schema";
import { isLiveTopic, type TopicRow } from "@/library/join";
import { Text } from "@/theme/components/Text";
import { TextField } from "@/theme/components/TextField";
import { useTheme } from "@/theme/useTheme";
import { DOMAINS } from "@/topics/domains";
import { normalizeTopicName, slugify } from "@/topics/topicName";

import { haptic } from "./haptics";
import { BottomSheet } from "./BottomSheet";
import { Kicker } from "./Kicker";

type TopicChooserSheetProps = {
  visible: boolean;
  onClose: () => void;
  title: string;
  excludeTopicId?: string;
  onChoose: (topic: TopicRow) => void;
};

/** Pick one of the user's live topics, grouped by domain, with a filter field. */
export function TopicChooserSheet({ visible, onClose, title, excludeTopicId, onChoose }: TopicChooserSheetProps) {
  const theme = useTheme();
  const [query, setQuery] = useState("");
  const { data: topics } = useLiveQuery(db.select().from(schema.topics));

  const groups = useMemo(() => {
    const wanted = normalizeTopicName(query);
    const candidates = topics.filter(
      (topic) => isLiveTopic(topic) && topic.id !== excludeTopicId && normalizeTopicName(topic.name).includes(wanted),
    );
    return DOMAINS.map((domain) => ({
      domain,
      topics: candidates.filter((topic) => topic.domain === domain).sort((a, b) => a.name.localeCompare(b.name)),
    })).filter((group) => group.topics.length > 0);
  }, [topics, query, excludeTopicId]);

  return (
    <BottomSheet visible={visible} onClose={onClose} testID="topic-chooser-sheet">
      <Text variant="headline">{title}</Text>
      <TextField testID="topic-chooser-search" placeholder="Filter topics" value={query} onChangeText={setQuery} />
      <ScrollView style={{ maxHeight: 360 }} keyboardShouldPersistTaps="handled">
        {groups.map((group) => (
          <View key={group.domain} style={{ paddingTop: theme.spacing.md }}>
            <Kicker domain={group.domain} />
            {group.topics.map((topic) => (
              <Pressable
                key={topic.id}
                testID={`topic-choice-${slugify(topic.name)}`}
                onPress={() => {
                  haptic("selection");
                  onChoose(topic);
                  onClose();
                }}
                style={{ paddingVertical: theme.spacing.md }}
              >
                <Text>{topic.name}</Text>
              </Pressable>
            ))}
          </View>
        ))}
        {groups.length === 0 ? (
          <Text tone="ink3" style={{ paddingVertical: theme.spacing.md }}>
            No matching topics.
          </Text>
        ) : null}
      </ScrollView>
    </BottomSheet>
  );
}
