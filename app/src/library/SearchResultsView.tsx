import { useRouter } from "expo-router";
import { Linking, Pressable, View } from "react-native";

import { formatClock } from "@/ask/types";
import { timestampUrl } from "@/item/timestampLink";
import { TakeRow } from "@/takes/TakeRow";
import { useTakesData } from "@/takes/useTakesData";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { GroupedList } from "@/ui/GroupedList";
import { ItemRow } from "@/ui/ItemRow";
import { SourceRow } from "@/ui/SourceRow";

import type { LibraryData, LibrarySource } from "./join";
import type { ServerSearchResult } from "./serverSearch";

/** The server's search results: each row is the usual row for its kind with the passage that matched under it. */
export function SearchResultsView(props: { data: LibraryData; results: ServerSearchResult[] }) {
  const takes = useTakesData();
  const rows = props.results.flatMap((result) => {
    const row = resultRow({ result, data: props.data, takes });
    return row ? [<View key={`${result.itemKind}-${result.itemId}`}>{row}</View>] : [];
  });

  return <GroupedList>{rows}</GroupedList>;
}

function resultRow(input: {
  result: ServerSearchResult;
  data: LibraryData;
  takes: ReturnType<typeof useTakesData>;
}) {
  const { result, data } = input;

  if (result.itemKind === "source") {
    const source = data.sources.find((candidate) => candidate.id === result.itemId) ?? null;
    return <SourceResult result={result} source={source} />;
  }

  if (result.itemKind === "topic_primer") {
    const primer = data.topicPrimers.find((candidate) => candidate.id === result.itemId);
    const topic = primer ? data.topics.find((candidate) => candidate.id === primer.topicId) : undefined;
    if (!primer || !topic) return null;
    return <TopicPrimerResult result={result} topic={topic} opened={Boolean(primer.openedAt)} />;
  }

  const take = input.takes.find((candidate) => candidate.id === result.itemId);
  if (!take) return null;
  return (
    <View testID={`search-result-${result.itemId}`}>
      <TakeRow take={take} now={new Date()} />
      <Quote result={result} />
    </View>
  );
}

function SourceResult(props: { result: ServerSearchResult; source: LibrarySource | null }) {
  const router = useRouter();
  const { result, source } = props;
  const openSource = () => router.push({ pathname: "/source/[id]", params: { id: result.itemId } });

  // A passage with a time opens the player at that moment where the player supports it (Decision 11).
  const clock = result.startSeconds === null ? null : formatClock(result.startSeconds);
  const playerUrl = source && clock ? timestampUrl(source, clock) : null;
  const onQuotePress = playerUrl && playerUrl !== source?.url ? () => void Linking.openURL(playerUrl) : openSource;

  return (
    <View testID={`search-result-${result.itemId}`}>
      {source ? (
        <SourceRow source={source} testID={`source-row-${source.id}`} />
      ) : (
        <ItemRow
          artwork={{ imageUrl: null, domain: null, monogram: result.title.slice(0, 1).toUpperCase() }}
          kicker={{ domain: null }}
          title={result.title}
          meta=""
          onPress={openSource}
        />
      )}
      <Quote result={result} prefix={clock ? `${clock} · ` : ""} onPress={onQuotePress} />
    </View>
  );
}

function TopicPrimerResult(props: {
  result: ServerSearchResult;
  topic: LibraryData["topics"][number];
  opened: boolean;
}) {
  const router = useRouter();
  const { result, topic } = props;

  return (
    <View testID={`search-result-${result.itemId}`}>
      <ItemRow
        artwork={{ imageUrl: null, domain: topic.domain, monogram: "◆", unread: !props.opened }}
        kicker={{ domain: topic.domain, suffix: "Topic primer" }}
        title={topic.name}
        meta="Primer"
        onPress={() => router.push({ pathname: "/topic/[id]", params: { id: topic.id } })}
      />
      <Quote result={result} />
    </View>
  );
}

function Quote(props: { result: ServerSearchResult; prefix?: string; onPress?: () => void }) {
  const theme = useTheme();
  const text = (
    <Text testID={`search-quote-${props.result.itemId}`} variant="secondary" tone="ink2" numberOfLines={2}>
      {`${props.prefix ?? ""}${props.result.passage}`}
    </Text>
  );

  return (
    <View style={{ paddingBottom: theme.spacing.md }}>
      {props.onPress ? <Pressable onPress={props.onPress}>{text}</Pressable> : text}
    </View>
  );
}
