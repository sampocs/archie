import { and, eq, min } from "drizzle-orm";
import { useLiveQuery } from "drizzle-orm/expo-sqlite";
import { useRouter } from "expo-router";
import { Pressable, View } from "react-native";

import { db } from "@/db/client";
import * as schema from "@/db/schema";
import { Button } from "@/theme/components/Button";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { bookBadge, READING_STATE } from "@/ui/sourceLabels";
import type { SummaryContent } from "@/ui/summaryContent";

import { ItemBadgeLine } from "./ItemBadgeLine";
import { PrimerButton } from "./PrimerButton";
import { SectionTitle, SummarySections } from "./SummarySections";

type SourceRow = typeof schema.sources.$inferSelect;

type BookBodyProps = {
  source: SourceRow;
  summary: SummaryContent | null;
  primerWords: number | null;
  onFinish: () => void;
  onOpenNotes: () => void;
};

/**
 * A book's page below its title. Reading: the badge, the spoiler-free primer and Finished it; its cards come once it's
 * finished. Finished: the badge, the refresher, the owner's thoughts, the primer as background, and the imported notes.
 */
export function BookBody({ source, summary, primerWords, onFinish, onOpenNotes }: BookBodyProps) {
  const theme = useTheme();
  const router = useRouter();
  const finishedAt = useFinishedAt(source);

  if (source.state === READING_STATE) {
    return (
      <>
        <ItemBadgeLine source={source} label={bookBadge(source, finishedAt)} />
        <PrimerButton source={source} primerWords={primerWords} />
        <Button testID="book-finish" label="Finished it" onPress={onFinish} />
        <View style={{ gap: theme.spacing.sm }}>
          <SectionTitle>Cards</SectionTitle>
          <Text testID="book-cards-later" tone="ink2">
            Cards come when you finish the book.
          </Text>
        </View>
      </>
    );
  }

  return (
    <>
      <ItemBadgeLine source={source} label={bookBadge(source, finishedAt)} />
      {summary ? <SummarySections summary={summary} source={source} /> : null}
      {source.note ? (
        <View style={{ gap: theme.spacing.sm }}>
          <SectionTitle>Your note</SectionTitle>
          <Text testID="book-note" tone="ink2">
            {source.note}
          </Text>
        </View>
      ) : null}
      {primerWords !== null ? (
        <Pressable
          testID="book-background"
          onPress={() => router.push({ pathname: "/primer/[id]", params: { id: source.id } })}
          hitSlop={8}
        >
          <Text variant="headline">Background you might need ›</Text>
        </Pressable>
      ) : null}
      {source.noteMarkdown ? (
        <Pressable testID="book-notes" onPress={onOpenNotes} hitSlop={8}>
          <Text variant="headline">See your notes ›</Text>
        </Pressable>
      ) : null}
    </>
  );
}

// No finish time is synced, so a finished book dates from its first refresher (every version is kept on the phone),
// or from its last change while the refresher is still being written.
function useFinishedAt(source: SourceRow): string {
  const { data } = useLiveQuery(
    db
      .select({ first: min(schema.artifacts.createdAt) })
      .from(schema.artifacts)
      .where(and(eq(schema.artifacts.sourceId, source.id), eq(schema.artifacts.kind, "summary"))),
    [source.id],
  );
  return data[0]?.first ?? source.updatedAt;
}
