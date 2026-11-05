import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { Pressable, View } from "react-native";

import { requestTopicPrimer, restoreTopic, setPrimerOpened } from "@/db/actions";
import { db } from "@/db/client";
import { isLiveTopic } from "@/library/join";
import { useLibraryData } from "@/library/useLibraryData";
import { statusTag } from "@/library/visibility";
import { requestSync } from "@/sync/useSync";
import { Button } from "@/theme/components/Button";
import { Card } from "@/theme/components/Card";
import { Screen } from "@/theme/components/Screen";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { asDomain } from "@/topics/domains";
import { TopicMenu } from "@/topics/TopicMenu";
import { GroupedList } from "@/ui/GroupedList";
import { haptic } from "@/ui/haptics";
import { Kicker } from "@/ui/Kicker";
import { Markdown } from "@/ui/Markdown";
import { useNow } from "@/ui/useNow";
import { kindLabel } from "@/ui/sourceLabels";
import { SourceRow } from "@/ui/SourceRow";

// After this long without a primer, the "writing" state gives way to "Write a primer" again.
const PRIMER_WAIT_MS = 10 * 60 * 1000;

export default function TopicScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const theme = useTheme();
  const data = useLibraryData();
  const now = useNow();
  const [menuOpen, setMenuOpen] = useState(false);
  const [primerOpen, setPrimerOpen] = useState(false);

  const topic = data.topics.find((candidate) => candidate.id === id);
  const primer = data.topicPrimers.find((candidate) => candidate.topicId === id);
  const mergedIntoId = topic?.mergedIntoId ?? null;

  // A merged topic no longer exists on its own; follow it to the winner.
  useEffect(() => {
    if (mergedIntoId) router.replace({ pathname: "/topic/[id]", params: { id: mergedIntoId } });
  }, [mergedIntoId, router]);

  // Opening the primer marks it opened (once), which clears its unread dot in Domains.
  const unopenedPrimerId = primerOpen && primer && !primer.openedAt ? primer.id : null;
  useEffect(() => {
    if (!unopenedPrimerId) return;
    setPrimerOpened(db, "topic_primer", unopenedPrimerId, true);
    requestSync();
  }, [unopenedPrimerId]);

  if (!topic || mergedIntoId) return <Screen title="Topic" onBack={router.back} />;

  const sources = data.sources.filter((source) => source.topicId === topic.id);
  const done = sources.filter((source) => source.state === "consumed").length;
  const queued = sources.filter((source) => source.state === "queued").length;
  const writing =
    !primer && topic.primerRequestedAt !== null && now.getTime() - new Date(topic.primerRequestedAt).getTime() < PRIMER_WAIT_MS;

  const menuButton = isLiveTopic(topic) ? (
    <Pressable testID="topic-more" accessibilityLabel="Topic actions" hitSlop={12} onPress={() => setMenuOpen(true)}>
      <Text variant="largeTitle" tone="ink2">
        •••
      </Text>
    </Pressable>
  ) : undefined;

  return (
    <Screen title="" onBack={router.back} headerRight={menuButton}>
      <View style={{ gap: theme.spacing.sm }}>
        <Kicker domain={topic.domain} suffix="Topic" />
        <Text variant="articleTitle" testID="topic-name">
          {topic.name}
        </Text>
        <Text tone="ink3" testID="topic-counts">
          {`${sources.length} items · ${done} done · ${queued} queued`}
        </Text>
      </View>

      {topic.removedAt ? (
        <Card style={{ gap: theme.spacing.md }}>
          <Text>You removed this topic.</Text>
          <Button
            testID="topic-restore"
            label="Restore"
            variant="secondary"
            onPress={() => {
              restoreTopic(db, topic.id);
              haptic("success");
              requestSync();
            }}
          />
        </Card>
      ) : primer ? (
        <View style={{ gap: theme.spacing.md }}>
          <Pressable
            testID="topic-primer-toggle"
            onPress={() => {
              haptic("selection");
              setPrimerOpen((open) => !open);
            }}
          >
            <Text variant="headline" domain={asDomain(topic.domain)}>
              {primerOpen ? "▾ Primer" : "▸ Primer"}
            </Text>
          </Pressable>
          {primerOpen ? <Markdown text={(JSON.parse(primer.content) as { markdown: string }).markdown} /> : null}
        </View>
      ) : writing ? (
        <Card>
          <Text testID="topic-primer-writing" tone="ink2">
            Writing a primer… ready in a minute or two.
          </Text>
        </Card>
      ) : (
        <Pressable
          testID="topic-write-primer"
          onPress={() => {
            requestTopicPrimer(db, topic.id);
            haptic("success");
            requestSync();
          }}
        >
          <Card style={{ gap: theme.spacing.xs }}>
            <Text variant="headline">Write a primer on this topic</Text>
            <Text tone="ink2">The general background, about 6 minutes to read.</Text>
          </Card>
        </Pressable>
      )}

      {sources.length > 0 ? (
        <GroupedList title="Items">
          {sources.map((source) => (
            <SourceRow
              key={source.id}
              source={source}
              testID={`topic-item-${source.id}`}
              meta={`${kindLabel(source.kind)} · ${statusTag(source)}`}
            />
          ))}
        </GroupedList>
      ) : null}

      <TopicMenu
        topic={topic}
        topics={data.topics}
        visible={menuOpen}
        onClose={() => setMenuOpen(false)}
        followMerge
      />
    </Screen>
  );
}
