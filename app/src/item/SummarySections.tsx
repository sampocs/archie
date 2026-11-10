import { Linking, Pressable, StyleSheet, View } from "react-native";

import type * as schema from "@/db/schema";
import { splitFacts } from "@/summary/figures";
import { Card } from "@/theme/components/Card";
import { Text } from "@/theme/components/Text";
import { fontFamily } from "@/theme/type";
import { useTheme } from "@/theme/useTheme";
import { haptic } from "@/ui/haptics";
import { InlineMarkdown } from "@/ui/Markdown";
import type { SummaryContent } from "@/ui/summaryContent";

import { timestampUrl } from "./timestampLink";

type SourceRow = typeof schema.sources.$inferSelect;

export function SectionTitle({ children }: { children: string }) {
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

export function SummarySections({ summary, source }: { summary: SummaryContent; source: SourceRow }) {
  const theme = useTheme();

  return (
    <>
      <View style={{ gap: theme.spacing.sm }}>
        <InlineMarkdown testID="source-gist" text={summary.gist} />
      </View>

      {summary.key_ideas.length > 0 ? (
        <View style={{ gap: theme.spacing.md }}>
          <SectionTitle>Key ideas</SectionTitle>
          {summary.key_ideas.map((item, index) => (
            <View key={index} style={{ flexDirection: "row", gap: theme.spacing.sm, alignItems: "flex-start" }}>
              <Text variant="readingBody">{index + 1}.</Text>
              <InlineMarkdown text={item.idea} style={{ flex: 1 }} />
              <TimestampChip timestamp={item.timestamp} source={source} />
            </View>
          ))}
        </View>
      ) : null}

      {summary.numbers.length > 0 ? (
        <View style={{ gap: theme.spacing.sm }}>
          <SectionTitle>Rough numbers</SectionTitle>
          <Card testID="rough-numbers" style={{ paddingVertical: 0 }}>
            {summary.numbers.map((item, index) => (
              <View
                key={index}
                style={[
                  { flexDirection: "row", gap: theme.spacing.sm, alignItems: "flex-start", paddingVertical: theme.spacing.md },
                  index > 0 ? { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: theme.colors.line } : null,
                ]}
              >
                <Text style={{ flex: 1 }}>
                  {splitFacts(item.fact).map((segment, segmentIndex) => (
                    <Text key={segmentIndex} style={segment.figure ? { fontFamily: fontFamily.mono } : null}>
                      {segment.text}
                    </Text>
                  ))}
                </Text>
                <TimestampChip timestamp={item.timestamp} source={source} />
              </View>
            ))}
          </Card>
        </View>
      ) : null}
    </>
  );
}
