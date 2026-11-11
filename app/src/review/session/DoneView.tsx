import { useRouter } from "expo-router";
import { useMemo } from "react";
import { View } from "react-native";

import { type ReviewData } from "@/review/eligibility";
import { doneSummaryLine, elapsedMinutes } from "@/review/sessionFlow";
import { aheadSummary, dueSummary, minutesFor, nextReview } from "@/review/summary";
import { gradedCount, type Tally } from "@/review/tally";
import { KeepGoing } from "@/review/ui/KeepGoing";
import { Button } from "@/theme/components/Button";
import { Card } from "@/theme/components/Card";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";

type DoneViewProps = { tally: Tally; startedAt: Date; data: ReviewData; dailyLimit: number | null };

/** The end of a session (mock 03): how it went, then more practice or back to Today. */
export function DoneView({ tally, startedAt, data, dailyLimit }: DoneViewProps) {
  const theme = useTheme();
  const router = useRouter();
  // Fixed when the view first shows, so the minutes don't tick up while it stays open.
  const finishedAt = useMemo(() => new Date(), []);
  const summary = doneSummaryLine(
    gradedCount(tally),
    elapsedMinutes(startedAt, finishedAt),
    nextReview(data, finishedAt),
    finishedAt,
  );
  const ahead = aheadSummary(data, finishedAt);
  const waiting = dueSummary(data, finishedAt, dailyLimit).waiting;
  // A Keep going session takes up to a day's limit of the waiting cards.
  const moreMinutes = minutesFor(Math.min(waiting, dailyLimit ?? waiting));

  const rows = [
    { key: "got_it", label: "Got it", count: tally.gotIt, color: theme.signals.gotIt },
    { key: "partly", label: "Partly", count: tally.partly, color: theme.signals.partly },
    { key: "missed", label: "Missed", count: tally.missed, color: theme.signals.missed },
    { key: "dropped", label: "Dropped", count: tally.dropped, color: theme.colors.ink3 },
  ];

  return (
    <View testID="review-done" style={{ gap: theme.spacing.section }}>
      <View style={{ gap: theme.spacing.sm, paddingHorizontal: theme.spacing.gutterText - theme.spacing.gutterCards }}>
        <Text variant="largeTitle">Done.</Text>
        <Text testID="done-summary" tone="ink2">
          {summary}
        </Text>
      </View>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: theme.spacing.sm }}>
        {rows.map((row) => (
          <Card key={row.key} testID={`tally-${row.key}`} style={{ flexBasis: "48%", flexGrow: 1, gap: 2 }}>
            <Text variant="articleTitle" style={{ color: row.color, fontSize: 22 }}>
              {String(row.count)}
            </Text>
            <Text variant="secondary" tone="ink3">
              {row.label}
            </Text>
          </Card>
        ))}
      </View>
      <KeepGoing
        waiting={waiting}
        moreMinutes={moreMinutes}
        onMore={() => router.replace({ pathname: "/review/session", params: { mode: "more" } })}
        aheadCount={ahead.count}
        aheadBy={ahead.by}
        onAhead={() => router.replace({ pathname: "/review/session", params: { mode: "ahead" } })}
        // Topics now live on the Review tab's browse list.
        onTopic={() =>
          router.dismissTo({ pathname: "/(tabs)/review", params: { browse: "topics", at: String(Date.now()) } })
        }
      />
      <Button testID="done-back-today" label="Back to Today" onPress={() => router.dismissTo("/(tabs)/today")} />
    </View>
  );
}
