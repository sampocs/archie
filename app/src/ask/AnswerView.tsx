import { eq } from "drizzle-orm";
import { useRouter } from "expo-router";
import { Linking, Pressable, View } from "react-native";

import { db } from "@/db/client";
import * as schema from "@/db/schema";
import { timestampUrl } from "@/item/timestampLink";
import { Button } from "@/theme/components/Button";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { Markdown } from "@/ui/Markdown";

import { chipText, type Section } from "./sections";
import { ANSWER_LABEL_TEXT, formatClock, type Citation } from "./types";

type AnswerViewProps = {
  sections: Section[];
  streamingText?: string;
  searching?: "library" | "web" | null;
  failed?: boolean;
  onRetry?: () => void;
  // Set only for a complete stored answer.
  onMakeCard?: () => void;
  index: number;
};

const SEARCHING_TEXT = { library: "Searching your library…", web: "Searching the web…" } as const;

/** One answer: its labelled sections with citation chips, the text still streaming, and how it ended. */
export function AnswerView({ sections, streamingText, searching, failed, onRetry, onMakeCard, index }: AnswerViewProps) {
  const theme = useTheme();
  const router = useRouter();

  return (
    <View testID={`chat-answer-${index}`} style={{ gap: theme.spacing.lg }}>
      {sections.map((section, sectionIndex) => (
        <View key={sectionIndex} testID={`answer-section-${section.label}`} style={{ gap: theme.spacing.sm }}>
          <Text variant="kicker" tone="ink2">
            {ANSWER_LABEL_TEXT[section.label]}
          </Text>
          <Markdown text={section.text.trim()} />
          {section.citations.length > 0 ? (
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: theme.spacing.sm }}>
              {section.citations.map((citation, chipIndex) => (
                <Pressable
                  key={chipIndex}
                  testID="answer-chip"
                  onPress={() => openCitation(citation, router)}
                  style={{
                    backgroundColor: theme.colors.press,
                    borderRadius: theme.radii.chip,
                    paddingHorizontal: theme.spacing.md,
                    paddingVertical: theme.spacing.xs,
                  }}
                >
                  <Text variant="secondary">{chipText(citation)}</Text>
                </Pressable>
              ))}
            </View>
          ) : null}
        </View>
      ))}
      {streamingText ? <Markdown text={streamingText.trim()} /> : null}
      {searching ? (
        <Text testID="chat-searching" tone="ink3">
          {SEARCHING_TEXT[searching]}
        </Text>
      ) : null}
      {failed ? (
        <Pressable testID="chat-retry" onPress={onRetry} hitSlop={8}>
          <Text testID="chat-failed" tone="ink2">
            Didn't finish. Try again
          </Text>
        </Pressable>
      ) : null}
      {onMakeCard ? (
        <Button testID={`answer-make-card-${index}`} variant="secondary" label="Make a card" onPress={onMakeCard} />
      ) : null}
    </View>
  );
}

// A web chip links out; a library chip opens its item, or the player at the passage's time when it has one.
function openCitation(citation: Citation, router: ReturnType<typeof useRouter>): void {
  if (citation.kind === "web") {
    void Linking.openURL(citation.url);
    return;
  }
  if (citation.source_id) {
    const source = db.select().from(schema.sources).where(eq(schema.sources.id, citation.source_id)).get();
    if (source && citation.start_seconds !== null) {
      const atTime = timestampUrl(source, formatClock(citation.start_seconds));
      if (atTime !== source.url) {
        void Linking.openURL(atTime);
        return;
      }
    }
    router.push({ pathname: "/source/[id]", params: { id: citation.source_id } });
    return;
  }
  if (citation.topic_primer_id) {
    const primer = db
      .select()
      .from(schema.topicPrimers)
      .where(eq(schema.topicPrimers.id, citation.topic_primer_id))
      .get();
    if (primer) router.push({ pathname: "/topic/[id]", params: { id: primer.topicId } });
    return;
  }
  if (citation.take_id) router.push({ pathname: "/take/[id]", params: { id: citation.take_id } });
}
