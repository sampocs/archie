import { and, eq } from "drizzle-orm";
import { useLiveQuery } from "drizzle-orm/expo-sqlite";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect } from "react";
import { Pressable, View } from "react-native";

import { finishPrimer, setPrimerOpened } from "@/db/actions";
import { db } from "@/db/client";
import * as schema from "@/db/schema";
import { primerMarkdown, readingMinutes, wordCount } from "@/library/primer";
import { requestSync } from "@/sync/useSync";
import { Button } from "@/theme/components/Button";
import { Screen } from "@/theme/components/Screen";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { ArtworkTile } from "@/ui/ArtworkTile";
import { haptic } from "@/ui/haptics";
import { Kicker } from "@/ui/Kicker";
import { Markdown } from "@/ui/Markdown";
import { PRIMER_MONOGRAM } from "@/ui/monogram";

/** A source's primer on its own: a link back to its item, and "Mark as done" while it sits in the queue. */
export default function PrimerScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const theme = useTheme();
  const { data: sources } = useLiveQuery(db.select().from(schema.sources).where(eq(schema.sources.id, id)), [id]);
  const { data: primers } = useLiveQuery(
    db
      .select()
      .from(schema.artifacts)
      .where(
        and(eq(schema.artifacts.sourceId, id), eq(schema.artifacts.kind, "primer"), eq(schema.artifacts.isCurrent, 1)),
      ),
    [id],
  );

  const source = sources[0];
  const markdown = primers[0] ? primerMarkdown(primers[0].content) : null;
  const needsMark = markdown !== null && source !== undefined && source.primerOpenedAt === null;

  // Opening the primer marks it read; a queued one stays in the queue until "Mark as done".
  useEffect(() => {
    if (!needsMark) return;
    setPrimerOpened(db, "source", id, true);
    requestSync();
  }, [needsMark, id]);

  if (!source || source.deletedAt) return <Screen title="Primer" onBack={router.back} />;

  const title = source.title ?? source.url;
  const queued = source.primerQueuePosition !== null;

  return (
    <Screen title="" onBack={router.back}>
      <View style={{ flexDirection: "row", gap: theme.spacing.md, alignItems: "center" }}>
        <ArtworkTile imageUrl={null} domain={source.domain} monogram={PRIMER_MONOGRAM} size={92} />
        <View style={{ flex: 1, gap: theme.spacing.xs }}>
          <Kicker domain={source.domain} suffix="Primer" />
          <Text variant="secondary" tone="ink2">
            {markdown === null ? "Writing primer…" : `${readingMinutes(wordCount(markdown))} min read`}
          </Text>
        </View>
      </View>
      <Text testID="primer-title" variant="articleTitle">
        {`Primer: ${title}`}
      </Text>
      <Pressable
        testID="primer-for"
        hitSlop={8}
        onPress={() => router.push({ pathname: "/source/[id]", params: { id: source.id } })}
      >
        <Text variant="secondary" style={{ textDecorationLine: "underline" }}>
          {`For: ${title} ›`}
        </Text>
      </Pressable>
      {queued ? (
        <Button
          testID="primer-done"
          label="Mark as done"
          onPress={() => {
            finishPrimer(db, source.id);
            haptic("success");
            requestSync();
            router.back();
          }}
        />
      ) : null}
      {markdown === null ? null : (
        <View testID="primer-body">
          <Markdown text={markdown} />
        </View>
      )}
    </Screen>
  );
}
