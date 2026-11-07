import { and, eq, inArray, isNull } from "drizzle-orm";
import { useLiveQuery } from "drizzle-orm/expo-sqlite";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Pressable, StyleSheet, View } from "react-native";

import { parseBriefContent, storiesInOrder } from "@/brief/brief";
import { db } from "@/db/client";
import * as schema from "@/db/schema";
import { Card } from "@/theme/components/Card";
import { Screen } from "@/theme/components/Screen";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { WEEKDAYS } from "@/today/todayLabels";
import type { DomainName } from "@/topics/domains";
import { ArtworkTile } from "@/ui/ArtworkTile";
import { haptic } from "@/ui/haptics";
import { Kicker } from "@/ui/Kicker";
import { monogramFor } from "@/ui/monogram";
import { sentDate } from "@/ui/sourceLabels";

type SourceRow = typeof schema.sources.$inferSelect;

const SOURCE_ART_SIZE = 34;

/** One brief story, a step deeper: its fuller paragraph and the newsletters that covered it. */
export default function BriefStoryScreen() {
  const { index, brief: briefId } = useLocalSearchParams<{
    index: string;
    brief: string;
  }>();
  const router = useRouter();
  const theme = useTheme();
  const { data: briefs } = useLiveQuery(
    db.select().from(schema.briefs).where(eq(schema.briefs.id, briefId)),
    [briefId],
  );

  const content = briefs[0] ? parseBriefContent(briefs[0].content) : null;
  const entry = content ? storiesInOrder(content)[Number(index)] : undefined;
  const sourceIds = entry?.story.source_ids ?? [];
  const { data: sources } = useLiveQuery(
    db
      .select()
      .from(schema.sources)
      .where(
        and(
          inArray(schema.sources.id, sourceIds),
          isNull(schema.sources.deletedAt),
        ),
      ),
    [sourceIds.join(",")],
  );

  if (!entry) return <Screen title="Story" onBack={router.back} />;

  // Rows follow the story's own source order.
  const sourcesById = new Map(sources.map((source) => [source.id, source]));
  const covering = sourceIds.flatMap((id) => sourcesById.get(id) ?? []);

  return (
    <Screen title="" onBack={router.back}>
      <View style={{ gap: theme.spacing.sm, paddingHorizontal: 6 }}>
        <Kicker domain={entry.domain} suffix="Story" />
        <Text variant="articleTitle">{entry.story.headline}</Text>
      </View>
      <Text variant="readingBody" style={{ paddingHorizontal: 6 }}>
        {entry.story.detail}
      </Text>
      <View testID="story-covered-by" style={{ gap: theme.spacing.sm }}>
        <Text variant="monoLabel" tone="ink3" style={{ paddingHorizontal: 6 }}>
          Covered by
        </Text>
        <Card style={{ paddingVertical: 0 }}>
          {covering.map((source, position) => (
            <CoveringRow
              key={source.id}
              source={source}
              domain={entry.domain}
              first={position === 0}
            />
          ))}
        </Card>
      </View>
    </Screen>
  );
}

function CoveringRow({
  source,
  domain,
  first,
}: {
  source: SourceRow;
  domain: DomainName;
  first: boolean;
}) {
  const theme = useTheme();
  const router = useRouter();
  const subject = source.title ?? "Untitled";

  return (
    <Pressable
      testID={`story-source-${source.id}`}
      onPress={() => {
        haptic("light");
        router.push({ pathname: "/source/[id]", params: { id: source.id } });
      }}
      style={[
        {
          flexDirection: "row",
          alignItems: "center",
          gap: 10,
          paddingVertical: 11,
        },
        !first && {
          borderTopWidth: StyleSheet.hairlineWidth,
          borderTopColor: theme.colors.line,
        },
      ]}
    >
      <ArtworkTile
        imageUrl={null}
        domain={domain}
        monogram={monogramFor(source)}
        size={SOURCE_ART_SIZE}
      />
      <View style={{ flex: 1 }}>
        <Text variant="headline" style={{ fontSize: 14 }} numberOfLines={1}>
          {source.sender ?? "Newsletter"}
        </Text>
        <Text
          variant="secondary"
          tone="ink3"
          style={{ fontSize: 12.5 }}
          numberOfLines={1}
        >
          {`${subject} · ${WEEKDAYS[sentDate(source).getDay()]}`}
        </Text>
      </View>
    </Pressable>
  );
}
