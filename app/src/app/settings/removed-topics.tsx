import { useRouter } from "expo-router";
import { View } from "react-native";

import { restoreTopic } from "@/db/actions";
import { db } from "@/db/client";
import { useLibraryData } from "@/library/useLibraryData";
import { requestSync } from "@/sync/useSync";
import { Button } from "@/theme/components/Button";
import { Screen } from "@/theme/components/Screen";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { slugify } from "@/topics/topicName";
import { GroupedList } from "@/ui/GroupedList";
import { haptic } from "@/ui/haptics";
import { Kicker } from "@/ui/Kicker";

export default function RemovedTopicsScreen() {
  const router = useRouter();
  const theme = useTheme();
  const { topics } = useLibraryData();
  const removed = topics
    .filter((topic) => topic.removedAt && !topic.mergedIntoId)
    .sort((a, b) => a.name.localeCompare(b.name));

  return (
    <Screen title="Removed topics" onBack={router.back}>
      {removed.length === 0 ? (
        <Text testID="removed-topics-empty" tone="ink2">
          No removed topics.
        </Text>
      ) : (
        <GroupedList>
          {removed.map((topic) => (
            <View
              key={topic.id}
              style={{ flexDirection: "row", alignItems: "center", gap: theme.spacing.md, paddingVertical: theme.spacing.md }}
            >
              <View style={{ flex: 1 }}>
                <Kicker domain={topic.domain} />
                <Text>{topic.name}</Text>
              </View>
              <Button
                testID={`restore-${slugify(topic.name)}`}
                label="Restore"
                variant="secondary"
                onPress={() => {
                  restoreTopic(db, topic.id);
                  haptic("success");
                  requestSync();
                }}
              />
            </View>
          ))}
        </GroupedList>
      )}
    </Screen>
  );
}
