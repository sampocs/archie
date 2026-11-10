import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useMemo, useState } from "react";
import { View } from "react-native";

import {
  asBrowseMode,
  browsableCards,
  browseItems,
  browseTopics,
  type BrowseMode,
  missedCards,
  reviewStreak,
  searchCards,
} from "@/review/browse";
import type { ReviewData } from "@/review/eligibility";
import { cardsWord } from "@/review/labels";
import { orderCards } from "@/review/session";
import { aheadSummary, dueSummary, nextReview } from "@/review/summary";
import {
  BrowseModeControl,
  CardSearchResults,
  ItemsList,
  MissedList,
  TopicsList,
} from "@/review/ui/BrowseLists";
import { CaughtUpCard } from "@/review/ui/CaughtUpCard";
import { ReviewStartCard } from "@/review/ui/ReviewStartCard";
import { useBrowseMode } from "@/review/useBrowseMode";
import { useReviewData } from "@/review/useReviewData";
import { Screen } from "@/theme/components/Screen";
import { Text } from "@/theme/components/Text";
import { TextField } from "@/theme/components/TextField";
import { useTheme } from "@/theme/useTheme";
import { useNow } from "@/ui/useNow";

// A streak of one day isn't worth a label.
const MIN_STREAK_SHOWN = 2;

type SessionParams = { mode: string };

/** The Review tab: start a session (due, ahead or shuffled), then search and browse every card. */
export default function ReviewScreen() {
  const theme = useTheme();
  const router = useRouter();
  const now = useNow();
  const data = useReviewData();
  const params = useLocalSearchParams<{ browse?: string; at?: string }>();
  const [mode, setMode] = useBrowseMode();
  const [query, setQuery] = useState("");
  const cards = useMemo(() => browsableCards(data), [data]);
  const due = dueSummary(data, now);
  const streak = reviewStreak(data.reviews, now);
  const startSession = (session: SessionParams) => router.push({ pathname: "/review/session", params: session });

  // The session's Done screen links here to a browse mode (with a fresh `at`, so the same link works twice).
  useEffect(() => {
    if (params.browse) setMode(asBrowseMode(params.browse));
  }, [params.browse, params.at, setMode]);

  return (
    <Screen
      title="Review"
      headerRight={
        streak >= MIN_STREAK_SHOWN ? (
          <Text testID="review-streak" variant="monoLabel" tone="ink3">{`${streak}-day streak`}</Text>
        ) : null
      }
    >
      {due.count > 0 ? (
        <ReviewStartCard
          testID="review-tab-start"
          count={due.count}
          foundations={due.foundations}
          onPress={() => startSession({ mode: "due" })}
        />
      ) : (
        <CaughtUpCard
          cardCount={cards.length}
          next={nextReview(data, now)}
          aheadCount={aheadSummary(data, now).count}
          now={now}
          onAhead={() => startSession({ mode: "ahead" })}
          onShuffle={() => startSession({ mode: "shuffle" })}
        />
      )}

      {cards.length > 0 ? (
        <View style={{ gap: theme.spacing.md }}>
          <TextField
            testID="review-search"
            placeholder={`Search ${cardsWord(cards.length)}`}
            value={query}
            onChangeText={setQuery}
            autoCorrect={false}
            clearButtonMode="while-editing"
          />
          {query.trim() !== "" ? (
            <CardSearchResults cards={orderCards(searchCards(cards, query))} data={data} now={now} />
          ) : (
            <>
              <BrowseModeControl mode={mode} onChange={setMode} />
              <BrowsePanel mode={mode} data={data} now={now} />
            </>
          )}
        </View>
      ) : null}
    </Screen>
  );
}

function BrowsePanel({ mode, data, now }: { mode: BrowseMode; data: ReviewData; now: Date }) {
  switch (mode) {
    case "topics":
      return <TopicsList rows={browseTopics(data, now)} />;
    case "items":
      return <ItemsList rows={browseItems(data, now)} />;
    case "missed":
      return <MissedList entries={missedCards(data, now)} data={data} now={now} />;
  }
}
