import { and, desc, inArray, isNull } from "drizzle-orm";
import { useLiveQuery } from "drizzle-orm/expo-sqlite";
import { useRouter } from "expo-router";
import { useState } from "react";
import {
  NativeScrollEvent,
  NativeSyntheticEvent,
  Pressable,
  StyleSheet,
  View,
} from "react-native";

import {
  briefReadingMinutes,
  briefSinceLabel,
  briefTitle,
  essayCountLabel,
  isOpenBrief,
  parseBriefContent,
  storiesInOrder,
  storyCountLabel,
  type BriefContent,
  type NumberedStory,
} from "@/brief/brief";
import { finishBrief, readLater } from "@/db/actions";
import { db } from "@/db/client";
import * as schema from "@/db/schema";
import { requestSync } from "@/sync/useSync";
import { Button } from "@/theme/components/Button";
import { Card } from "@/theme/components/Card";
import { Screen } from "@/theme/components/Screen";
import { Text } from "@/theme/components/Text";
import { fontFamily } from "@/theme/type";
import { useTheme } from "@/theme/useTheme";
import type { DomainName } from "@/topics/domains";
import { haptic } from "@/ui/haptics";
import { useNow } from "@/ui/useNow";

type SourceRow = typeof schema.sources.$inferSelect;
type DomainSection = { domain: DomainName; stories: NumberedStory[] };

const PROGRESS_HEIGHT = 3;

/** The brief, read straight through: stories by domain, also happening, essays worth reading, then Done. */
export default function BriefScreen() {
  const router = useRouter();
  const theme = useTheme();
  const now = useNow();
  const [progress, setProgress] = useState(0);
  const { data: briefs } = useLiveQuery(
    db.select().from(schema.briefs).orderBy(desc(schema.briefs.createdAt)),
  );

  // The open brief; once Done closes it, the screen keeps showing it (now the newest done one) while it leaves.
  const brief = briefs.find(isOpenBrief) ?? briefs[0];
  const sourceIds = brief ? (JSON.parse(brief.sourceIds) as string[]) : [];
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
    [brief?.sourceIds],
  );
  const content = brief ? parseBriefContent(brief.content) : null;

  function trackProgress(event: NativeSyntheticEvent<NativeScrollEvent>): void {
    const { contentOffset, contentSize, layoutMeasurement } = event.nativeEvent;
    const scrollable = contentSize.height - layoutMeasurement.height;
    setProgress(
      scrollable > 0
        ? Math.min(1, Math.max(0, contentOffset.y / scrollable))
        : 1,
    );
  }

  const progressBar = (
    <View
      style={{
        height: PROGRESS_HEIGHT,
        borderRadius: PROGRESS_HEIGHT,
        marginHorizontal: theme.spacing.gutterText,
        backgroundColor: theme.colors.line,
        overflow: "hidden",
      }}
    >
      <View
        style={{
          height: "100%",
          width: `${progress * 100}%`,
          backgroundColor: theme.colors.chrome,
        }}
      />
    </View>
  );

  if (!brief || !content) return <Screen title="Brief" onBack={router.back} />;

  const minutes = `${briefReadingMinutes(content)} min`;
  const meta = brief.since
    ? `${briefSinceLabel(brief.since, now)} · ${minutes}`
    : minutes;

  const briefId = brief.id;
  function done(): void {
    finishBrief(db, briefId);
    haptic("success");
    requestSync();
    router.back();
  }

  return (
    <Screen
      title=""
      onBack={router.back}
      subheader={progressBar}
      onScroll={trackProgress}
    >
      <View testID="brief-screen" style={styles.titleRow}>
        <Text
          variant="headline"
          style={{
            fontSize: 20,
            letterSpacing: -0.03 * 20,
            fontFamily: fontFamily.bold,
          }}
        >
          {briefTitle(now)}
        </Text>
        <Text variant="monoLabel" tone="ink3">
          {meta}
        </Text>
      </View>

      {domainSections(content).map((section) => (
        <DomainStories
          key={section.stories[0].index}
          briefId={briefId}
          section={section}
        />
      ))}

      {content.also.length > 0 ? (
        <Card testID="brief-also" style={{ gap: 6 }}>
          <Text variant="monoLabel" tone="ink3">
            Also happening
          </Text>
          {content.also.map((line, index) => (
            <View
              key={index}
              style={{ flexDirection: "row", gap: theme.spacing.sm }}
            >
              <Text variant="secondary" tone="ink2" style={styles.alsoLine}>
                •
              </Text>
              <Text
                variant="secondary"
                tone="ink2"
                style={[styles.alsoLine, { flex: 1 }]}
              >
                {line.text}
              </Text>
            </View>
          ))}
        </Card>
      ) : null}

      {content.essays.length > 0 ? (
        <WorthReading content={content} sources={sources} />
      ) : null}

      {isOpenBrief(brief) ? (
        <View style={{ gap: theme.spacing.sm }}>
          <Button testID="brief-done" label="Done ✓" onPress={done} />
          <Text variant="secondary" tone="ink3" style={styles.hint}>
            Marks these stories and the essays you didn't queue as briefed. The
            next newsletter starts a new brief.
          </Text>
        </View>
      ) : null}
    </Screen>
  );
}

// Consecutive stories of one domain form its section; the content is stored in display order.
function domainSections(content: BriefContent): DomainSection[] {
  const sections: DomainSection[] = [];
  for (const entry of storiesInOrder(content)) {
    const last = sections.at(-1);
    if (last && last.domain === entry.domain) last.stories.push(entry);
    else sections.push({ domain: entry.domain, stories: [entry] });
  }
  return sections;
}

function DomainStories({
  briefId,
  section,
}: {
  briefId: string;
  section: DomainSection;
}) {
  const theme = useTheme();
  const router = useRouter();

  return (
    <View testID={`brief-domain-${section.domain}`} style={{ gap: 10 }}>
      <View style={styles.domainHeading}>
        <View
          style={[
            styles.domainSquare,
            { backgroundColor: theme.domains[section.domain] },
          ]}
        />
        <Text variant="headline" style={styles.domainLabel}>
          {section.domain}
        </Text>
        <Text variant="monoLabel" tone="ink3" style={{ textTransform: "none" }}>
          {storyCountLabel(section.stories.length)}
        </Text>
      </View>
      <Card style={{ paddingVertical: theme.spacing.xs }}>
        {section.stories.map(({ index, story }, position) => (
          <View
            key={index}
            testID={`brief-story-${index}`}
            style={[
              styles.story,
              position > 0 && {
                borderTopWidth: StyleSheet.hairlineWidth,
                borderTopColor: theme.colors.line,
              },
            ]}
          >
            <Text variant="headline" style={styles.storyHeadline}>
              {story.headline}
            </Text>
            <Text style={styles.storyBody}>
              {story.body}
              {story.why ? (
                <Text
                  tone="ink2"
                  style={styles.storyBody}
                >{` ${story.why}`}</Text>
              ) : null}
            </Text>
            <Pressable
              testID={`brief-story-${index}-sources`}
              hitSlop={8}
              onPress={() => {
                haptic("light");
                router.push({
                  pathname: "/brief/story/[index]",
                  params: { index: String(index), brief: briefId },
                });
              }}
              style={{ alignSelf: "flex-start", marginTop: 6 }}
            >
              <Text
                variant="secondary"
                tone="ink2"
                style={{ fontFamily: fontFamily.semibold, fontSize: 13 }}
              >
                {`Sources · ${story.source_ids.length} ›`}
              </Text>
            </Pressable>
          </View>
        ))}
      </Card>
    </View>
  );
}

function WorthReading({
  content,
  sources,
}: {
  content: BriefContent;
  sources: SourceRow[];
}) {
  const theme = useTheme();
  const router = useRouter();
  const sourcesById = new Map(sources.map((source) => [source.id, source]));

  function queue(sourceId: string): void {
    readLater(db, sourceId);
    haptic("success");
    requestSync();
  }

  return (
    <View style={{ gap: 10 }}>
      <View style={styles.titleRow}>
        <Text variant="headline">Worth reading</Text>
        <Text variant="monoLabel" tone="ink3">
          {essayCountLabel(content.essays.length)}
        </Text>
      </View>
      <Card style={{ paddingVertical: theme.spacing.xs }}>
        {content.essays.map((essay, position) => {
          const source = sourcesById.get(essay.source_id);
          const queued = source?.state === "queued";
          return (
            <Pressable
              key={essay.source_id}
              testID={`brief-essay-${essay.source_id}`}
              onPress={() =>
                router.push({
                  pathname: "/source/[id]",
                  params: { id: essay.source_id },
                })
              }
              style={[
                styles.essay,
                position > 0 && {
                  borderTopWidth: StyleSheet.hairlineWidth,
                  borderTopColor: theme.colors.line,
                },
              ]}
            >
              <View style={{ flex: 1, gap: 3 }}>
                <Text variant="kicker" tone="ink3" numberOfLines={1}>
                  {source?.sender ?? "Newsletter"}
                </Text>
                <Text
                  variant="headline"
                  style={{ fontSize: 14.5, lineHeight: 14.5 * 1.3 }}
                  numberOfLines={2}
                >
                  {source?.title ?? "Untitled"}
                </Text>
                <Text
                  variant="secondary"
                  tone="ink2"
                  style={{ fontSize: 12.5 }}
                >
                  {essay.pitch}
                </Text>
              </View>
              <Pressable
                testID={`brief-essay-${essay.source_id}-queue`}
                disabled={queued}
                hitSlop={8}
                onPress={() => queue(essay.source_id)}
              >
                <Text
                  variant="secondary"
                  style={{ fontFamily: fontFamily.semibold, fontSize: 13 }}
                >
                  {queued ? "✓ Queued" : "＋ Queue"}
                </Text>
              </Pressable>
            </Pressable>
          );
        })}
      </Card>
    </View>
  );
}

const styles = StyleSheet.create({
  titleRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "baseline",
    paddingHorizontal: 6,
  },
  domainHeading: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingHorizontal: 6,
  },
  domainSquare: { width: 10, height: 10, borderRadius: 3 },
  domainLabel: {
    flex: 1,
    fontFamily: fontFamily.bold,
    fontSize: 17,
    letterSpacing: -0.025 * 17,
  },
  story: { paddingVertical: 13 },
  storyHeadline: {
    fontSize: 15.5,
    letterSpacing: -0.015 * 15.5,
    lineHeight: 15.5 * 1.3,
    marginBottom: 4,
  },
  storyBody: { fontSize: 14.5, lineHeight: 14.5 * 1.55 },
  essay: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingVertical: 12,
  },
  alsoLine: { lineHeight: 13.5 * 1.5 },
  hint: {
    textAlign: "center",
    fontSize: 12.5,
    lineHeight: 12.5 * 1.4,
    paddingHorizontal: 14,
  },
});
