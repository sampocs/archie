import { and, asc, eq, isNull } from "drizzle-orm";
import { useLiveQuery } from "drizzle-orm/expo-sqlite";
import { useCallback, useEffect, useState } from "react";
import { Linking, Pressable, View } from "react-native";

import { db } from "@/db/client";
import { readLater, returnToInbox } from "@/db/actions";
import * as schema from "@/db/schema";
import { FullEmailSheet } from "@/item/FullEmailSheet";
import { ItemActions } from "@/item/ItemActions";
import { ItemBadgeLine } from "@/item/ItemBadgeLine";
import { ItemHeader, REACTION_LABELS } from "@/item/ItemHeader";
import { ItemMenu } from "@/item/ItemMenu";
import { timestampUrl } from "@/item/timestampLink";
import { requestSync } from "@/sync/useSync";
import { Card } from "@/theme/components/Card";
import { Screen } from "@/theme/components/Screen";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { FinishSheet } from "@/ui/FinishSheet";
import { haptic } from "@/ui/haptics";
import { primerMarkdown, wordCount } from "@/library/primer";
import { parseSummary, SummaryContent } from "@/ui/summaryContent";
import { Toast } from "@/ui/Toast";
import { useLocalSearchParams, useRouter } from "expo-router";

type SourceRow = typeof schema.sources.$inferSelect;

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

  const { data: topics } = useLiveQuery(
    db.select().from(schema.topics).where(eq(schema.topics.id, sources[0]?.topicId ?? "")),
    [sources[0]?.topicId],
  );
  const [finishOpen, setFinishOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [emailOpen, setEmailOpen] = useState(false);
  const [queuedToast, setQueuedToast] = useState(false);
  const hideToast = useCallback(() => setQueuedToast(false), []);

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
  const primerWords = primer ? wordCount(primerMarkdown(primer.content)) : null;

  function addToQueue(): void {
    readLater(db, source.id);
    haptic("success");
    requestSync();
    setQueuedToast(true);
  }

  return (
    <View style={{ flex: 1 }}>
      <Screen
        title=""
        onBack={router.back}
        headerRight={
          <Pressable testID="item-more" onPress={() => setMenuOpen(true)} hitSlop={12}>
            <Text variant="largeTitle">•••</Text>
          </Pressable>
        }
      >
        <ItemHeader source={source} topicName={topics[0]?.name ?? null} />
        <Text testID="item-title" variant="articleTitle">
          {source.title ?? source.url}
        </Text>
        <ItemBadgeLine source={source} onAddToQueue={addToQueue} />
        <ItemActions source={source} primerWords={primerWords} onFinish={() => setFinishOpen(true)} />
        {summaryContent ? <SummarySections summary={summaryContent} source={source} /> : null}
        {source.kind === "newsletter" ? <EmailLinks url={source.url} onOpenEmail={() => setEmailOpen(true)} /> : null}
        <NoteSection reaction={source.reaction} note={source.note} />
        {source.state === "consumed" && cards.length > 0 ? <CardsSection cards={cards} /> : null}
        <FinishSheet
          sourceId={source.id}
          primerWords={primerWords}
          visible={finishOpen}
          onClose={() => setFinishOpen(false)}
        />
        <ItemMenu source={source} visible={menuOpen} onClose={() => setMenuOpen(false)} />
        <FullEmailSheet sourceId={source.id} visible={emailOpen} onClose={() => setEmailOpen(false)} />
      </Screen>
      {/* Undo sends the reverse action rather than cancelling the first, which may already have synced. */}
      {queuedToast ? (
        <Toast
          message="Added to your queue"
          actionLabel="Undo"
          onAction={() => {
            returnToInbox(db, source.id);
            haptic("light");
            requestSync();
          }}
          onHide={hideToast}
        />
      ) : null}
    </View>
  );
}

// A newsletter whose web version the parser found keeps its real url; the rest have a `newsletter:` placeholder.
const NEWSLETTER_URL_PREFIX = "newsletter:";

function EmailLinks({ url, onOpenEmail }: { url: string; onOpenEmail: () => void }) {
  const theme = useTheme();

  return (
    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: theme.spacing.lg }}>
      <Pressable testID="item-full-email" onPress={onOpenEmail} hitSlop={8}>
        <Text variant="headline">Open the full email ›</Text>
      </Pressable>
      {url.startsWith(NEWSLETTER_URL_PREFIX) ? null : (
        <Pressable testID="item-open-original" onPress={() => void Linking.openURL(url)} hitSlop={8}>
          <Text variant="headline">Open original ›</Text>
        </Pressable>
      )}
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

function TimestampChip({ timestamp, source }: { timestamp: string | null; source: SourceRow }) {
  const theme = useTheme();
  if (!timestamp) return null;

  return (
    <Pressable
      testID="timestamp"
      hitSlop={8}
      onPress={() => {
        haptic("light");
        void Linking.openURL(timestampUrl(source, timestamp));
      }}
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
    </Pressable>
  );
}

function SummarySections({ summary, source }: { summary: SummaryContent; source: SourceRow }) {
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
              <TimestampChip timestamp={item.timestamp} source={source} />
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
              <TimestampChip timestamp={item.timestamp} source={source} />
            </View>
          ))}
        </View>
      ) : null}
    </>
  );
}

function NoteSection({ reaction, note }: { reaction: string | null; note: string | null }) {
  const theme = useTheme();
  if (!reaction && !note) return null;

  return (
    <View style={{ gap: theme.spacing.sm }}>
      <SectionTitle>Your note</SectionTitle>
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
