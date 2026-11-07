import { View } from "react-native";

import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { Markdown } from "@/ui/Markdown";

import { summaryAsMarkdown, type CardShape, type EditContent, type MarkdownShape, type SummaryShape } from "./content";
import type { EditTargetKind } from "./types";

/** One version's content, read-only: a summary as its sections, markdown rendered, a card's question and answer. */
export function VersionPreview({ kind, content }: { kind: EditTargetKind; content: EditContent | null }) {
  const theme = useTheme();
  if (content === null) return <Text tone="ink3">This version can't be shown.</Text>;
  if (kind === "card") {
    const card = content as CardShape;
    return (
      <View style={{ gap: theme.spacing.sm }}>
        <Text variant="kicker" tone="ink2">
          Question
        </Text>
        <Text>{card.question}</Text>
        <Text variant="kicker" tone="ink2">
          Answer
        </Text>
        <Text>{card.answer}</Text>
      </View>
    );
  }
  const markdown = kind === "summary" ? summaryAsMarkdown(content as SummaryShape) : (content as MarkdownShape).markdown;
  return <Markdown text={markdown} />;
}
