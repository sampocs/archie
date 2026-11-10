import { eq } from "drizzle-orm";
import { useLiveQuery } from "drizzle-orm/expo-sqlite";
import { useEffect, useState } from "react";
import { Pressable, ScrollView, useWindowDimensions, View } from "react-native";

import { db } from "@/db/client";
import * as schema from "@/db/schema";
import { SummarySections } from "@/item/SummarySections";
import { Button } from "@/theme/components/Button";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { asDomain } from "@/topics/domains";
import { BottomSheet } from "@/ui/BottomSheet";
import { Kicker } from "@/ui/Kicker";
import { Markdown } from "@/ui/Markdown";
import { CHAT_KIND, colorDomain, kindLabel, longDate } from "@/ui/sourceLabels";
import { parseSummary } from "@/ui/summaryContent";

const SHEET_BODY_HEIGHT_SHARE = 0.75;

type ItemSheetProps = { sourceId: string; visible: boolean; onClose: () => void };

/** The item a chat is about, beside the chat: its write-up (or the original note), all read from the synced tables. */
export function ItemSheet({ sourceId, visible, onClose }: ItemSheetProps) {
  const theme = useTheme();
  const { height } = useWindowDimensions();
  const [showOriginal, setShowOriginal] = useState(false);
  const { data: sources } = useLiveQuery(db.select().from(schema.sources).where(eq(schema.sources.id, sourceId)), [
    sourceId,
  ]);
  const { data: artifacts } = useLiveQuery(
    db.select().from(schema.artifacts).where(eq(schema.artifacts.sourceId, sourceId)),
    [sourceId],
  );

  // Each opening starts on the write-up.
  useEffect(() => {
    if (visible) setShowOriginal(false);
  }, [visible]);

  const source = sources[0];
  if (!source) return null;

  const summary = artifacts.find((artifact) => artifact.kind === "summary" && artifact.isCurrent === 1);
  const summaryContent = summary ? parseSummary(summary.content) : null;
  const isNote = source.kind === "note";
  const original = isNote ? source.noteMarkdown : null;
  const originalShown = original !== null && (showOriginal || summaryContent === null);
  const kicker = isNote
    ? { label: "Notes", suffix: source.domain ? asDomain(source.domain) : undefined }
    : source.kind === CHAT_KIND
      ? { label: kindLabel(CHAT_KIND), suffix: undefined }
      : { label: undefined, suffix: kindLabel(source.kind) };

  return (
    <BottomSheet visible={visible} onClose={onClose} testID="item-sheet">
      <Kicker domain={colorDomain(source)} label={kicker.label} suffix={kicker.suffix} />
      <Text variant="articleTitle">{source.title ?? source.url}</Text>
      <ScrollView style={{ maxHeight: height * SHEET_BODY_HEIGHT_SHARE }}>
        <View style={{ gap: theme.spacing.lg }}>
          {originalShown ? (
            <>
              {summaryContent ? (
                <Pressable testID="item-sheet-writeup" onPress={() => setShowOriginal(false)} hitSlop={8}>
                  <Text variant="headline">‹ Write-up</Text>
                </Pressable>
              ) : null}
              <Text variant="headline">Your original note</Text>
              <Text variant="secondary" tone="ink2">
                {`From Bear · last edited ${longDate(source.noteEditedAt ?? source.createdAt)}`}
              </Text>
              <Markdown text={original} />
            </>
          ) : summaryContent ? (
            <>
              <SummarySections summary={summaryContent} source={source} />
              {original ? (
                <Pressable testID="item-sheet-original" onPress={() => setShowOriginal(true)} hitSlop={8}>
                  <Text variant="headline">See original note ›</Text>
                </Pressable>
              ) : null}
            </>
          ) : (
            <Text tone="ink2">Archie's write-up is on its way</Text>
          )}
        </View>
      </ScrollView>
      <Button testID="item-sheet-done" label="Done" onPress={onClose} />
    </BottomSheet>
  );
}
