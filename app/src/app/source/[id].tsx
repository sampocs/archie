import { and, asc, eq, isNull } from "drizzle-orm";
import { useLiveQuery } from "drizzle-orm/expo-sqlite";
import { useEffect, useState } from "react";
import { Pressable, View } from "react-native";

import { db } from "@/db/client";
import * as schema from "@/db/schema";
import { Card } from "@/theme/components/Card";
import { Screen } from "@/theme/components/Screen";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { Markdown } from "@/ui/Markdown";
import { ProcessingLine } from "@/ui/ProcessingLine";
import { sourceByline } from "@/ui/sourceLabels";
import { parseSummary, SummaryContent } from "@/ui/summaryContent";
import { useLocalSearchParams, useRouter } from "expo-router";


const REACTION_LABELS: Record<string, string> = { easy: "Easy", mostly: "Mostly followed", lost: "Parts lost me" };

export default function SourceScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const { data: sources } = useLiveQuery(db.select().from(schema.sources).where(eq(schema.sources.id, id)), [id]);
  const { data: artifacts } = useLiveQuery(
    db
      .select()
      .from(schema.artifacts)
      .where(and(eq(schema.artifacts.sourceId, id), eq(schema.artifacts.isCurrent, 1))),
    [id],
  );
  const { data: cards } = useLiveQuery(
    db
      .select()
      .from(schema.cards)
      .where(and(eq(schema.cards.sourceId, id), isNull(schema.cards.deletedAt)))
      .orderBy(asc(schema.cards.createdAt)),
    [id],
  );

  const source = sources[0];
  const mergedIntoId = source?.deletedAt ? source.mergedIntoId : null;

  // A duplicate share is tombstoned and points at the source that won; follow it instead of showing the dead row.
  useEffect(() => {
    if (mergedIntoId) router.replace(`/source/${mergedIntoId}`);
  }, [mergedIntoId, router]);

  if (!source || source.deletedAt) return <Screen title="Source" />;

  const summary = artifacts.find((artifact) => artifact.kind === "summary");
  const primer = artifacts.find((artifact) => artifact.kind === "primer");
  const summaryContent = summary ? parseSummary(summary.content) : null;
  const primerMarkdown = primer ? (JSON.parse(primer.content) as { markdown: string }).markdown : null;

  return (
    <Screen title={source.title ?? "Source"}>
      <SourceHeader source={source} />
      {summaryContent ? <SummarySections summary={summaryContent} /> : null}
      {primerMarkdown ? <PrimerSection markdown={primerMarkdown} /> : null}
      <ReactionSection reaction={source.reaction} note={source.note} />
      {cards.length > 0 ? <CardsSection cards={cards} /> : null}
    </Screen>
  );
}

function SourceHeader({ source }: { source: typeof schema.sources.$inferSelect }) {
  const theme = useTheme();

  return (
    <View style={{ gap: theme.spacing.sm }}>
      <Text variant="secondary" tone="ink3">
        {source.kind} · {sourceByline(source)}
      </Text>
      <ProcessingLine source={source} />
    </View>
  );
}

function SectionTitle({ children }: { children: string }) {
  return (
    <Text variant="kicker" tone="ink2">
      {children}
    </Text>
  );
}

function TimestampChip({ timestamp }: { timestamp: string | null }) {
  const theme = useTheme();
  if (!timestamp) return null;

  return (
    <View
      testID="timestamp"
      style={{
        backgroundColor: theme.colors.press,
        borderRadius: theme.radii.chipSmall,
        paddingHorizontal: theme.spacing.sm,
        paddingVertical: theme.spacing.xs,
      }}
    >
      <Text variant="monoLabel" tone="ink2">
        {timestamp}
      </Text>
    </View>
  );
}

function SummarySections({ summary }: { summary: SummaryContent }) {
  const theme = useTheme();

  return (
    <>
      <View style={{ gap: theme.spacing.sm }}>
        <Text testID="source-gist" variant="readingBody">
          {summary.gist}
        </Text>
      </View>

      {summary.key_ideas.length > 0 ? (
        <View style={{ gap: theme.spacing.md }}>
          <SectionTitle>Key ideas</SectionTitle>
          {summary.key_ideas.map((item, index) => (
            <View key={index} style={{ flexDirection: "row", gap: theme.spacing.sm, alignItems: "flex-start" }}>
              <Text variant="readingBody">{index + 1}.</Text>
              <Text variant="readingBody" style={{ flex: 1 }}>
                {item.idea}
              </Text>
              <TimestampChip timestamp={item.timestamp} />
            </View>
          ))}
        </View>
      ) : null}

      {summary.numbers.length > 0 ? (
        <View style={{ gap: theme.spacing.md }}>
          <SectionTitle>Rough numbers</SectionTitle>
          {summary.numbers.map((item, index) => (
            <View key={index} style={{ flexDirection: "row", gap: theme.spacing.sm, alignItems: "flex-start" }}>
              <Text variant="monoLabel" style={{ flex: 1, textTransform: "none" }}>
                {item.fact}
              </Text>
              <TimestampChip timestamp={item.timestamp} />
            </View>
          ))}
        </View>
      ) : null}
    </>
  );
}

function PrimerSection({ markdown }: { markdown: string }) {
  const theme = useTheme();
  const [open, setOpen] = useState(false);

  return (
    <View testID="source-primer" style={{ gap: theme.spacing.md }}>
      <Pressable testID="primer-toggle" onPress={() => setOpen((current) => !current)} hitSlop={8}>
        <Text variant="headline">{open ? "▾" : "▸"} Background you might need</Text>
      </Pressable>
      {open ? <Markdown text={markdown} /> : null}
    </View>
  );
}

function ReactionSection({ reaction, note }: { reaction: string | null; note: string | null }) {
  const theme = useTheme();
  if (!reaction && !note) return null;

  return (
    <View style={{ gap: theme.spacing.sm }}>
      <SectionTitle>Your take</SectionTitle>
      {reaction ? <Text>{REACTION_LABELS[reaction] ?? reaction}</Text> : null}
      {note ? <Text tone="ink2">{note}</Text> : null}
    </View>
  );
}

function CardsSection({ cards }: { cards: (typeof schema.cards.$inferSelect)[] }) {
  const theme = useTheme();

  return (
    <View style={{ gap: theme.spacing.md }}>
      <SectionTitle>Cards from this</SectionTitle>
      {cards.map((card) => (
        <Card key={card.id} testID={`card-${card.id}`} style={{ gap: theme.spacing.sm }}>
          <Text variant="headline">{card.question}</Text>
          <Text tone="ink2">{card.answer}</Text>
        </Card>
      ))}
    </View>
  );
}
