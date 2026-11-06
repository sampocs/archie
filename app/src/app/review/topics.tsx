import { useRouter } from "expo-router";
import { Pressable, View } from "react-native";

import { cardsWord } from "@/review/labels";
import { topicPractice } from "@/review/summary";
import { useReviewData } from "@/review/useReviewData";
import { Screen } from "@/theme/components/Screen";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { slugify } from "@/topics/topicName";
import { GroupedList } from "@/ui/GroupedList";
import { Kicker } from "@/ui/Kicker";

export default function PracticeTopicScreen() {
  const theme = useTheme();
  const router = useRouter();
  const topics = topicPractice(useReviewData());

  return (
    <Screen title="Practice a topic" onBack={router.back}>
      {topics.length === 0 ? (
        <Text testID="practice-empty" tone="ink2">
          No topics have cards to practice yet.
        </Text>
      ) : (
        <GroupedList>
          {topics.map(({ topic, count }) => (
            <Pressable
              key={topic.id}
              testID={`practice-topic-${slugify(topic.name)}`}
              accessibilityRole="button"
              onPress={() => router.push({ pathname: "/review/session", params: { mode: "topic", id: topic.id } })}
              style={{
                flexDirection: "row",
                justifyContent: "space-between",
                alignItems: "center",
                paddingVertical: theme.spacing.md,
              }}
            >
              <View style={{ flex: 1, gap: theme.spacing.xs }}>
                <Kicker domain={topic.domain} />
                <Text>{topic.name}</Text>
              </View>
              <Text variant="secondary" tone="ink3">
                {cardsWord(count)}
              </Text>
            </Pressable>
          ))}
        </GroupedList>
      )}
    </Screen>
  );
}
