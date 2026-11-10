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
  // Derived from the whole log and card set, so they're recomputed only when the data or the clock changes, not on
  // every keystroke in the search box.
  const due = useMemo(() => dueSummary(data, now), [data, now]);
  const streak = useMemo(() => reviewStreak(data.reviews, now), [data, now]);
  const next = useMemo(() => nextReview(data, now), [data, now]);
  const aheadCount = useMemo(() => aheadSummary(data, now).count, [data, now]);
  const searchResults = useMemo(() => orderCards(searchCards(cards, query)), [cards, query]);
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
          onPress={() => startSession({ mode: "due" })}
        />
      ) : (
        <CaughtUpCard
          cardCount={cards.length}
          next={next}
          aheadCount={aheadCount}
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
            <CardSearchResults cards={searchResults} data={data} now={now} />
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

// Each list is computed in its own component so only the visible mode's work runs, and memoised so a re-render with
// the same data and clock (typing, toggling) doesn't redo it.
function BrowsePanel({ mode, data, now }: { mode: BrowseMode; data: ReviewData; now: Date }) {
  switch (mode) {
    case "topics":
      return <TopicsPanel data={data} now={now} />;
    case "items":
      return <ItemsPanel data={data} now={now} />;
    case "missed":
      return <MissedPanel data={data} now={now} />;
  }
}

function TopicsPanel({ data, now }: { data: ReviewData; now: Date }) {
  const rows = useMemo(() => browseTopics(data, now), [data, now]);
  return <TopicsList rows={rows} />;
}

function ItemsPanel({ data, now }: { data: ReviewData; now: Date }) {
  const rows = useMemo(() => browseItems(data, now), [data, now]);
  return <ItemsList rows={rows} />;
}

function MissedPanel({ data, now }: { data: ReviewData; now: Date }) {
  const entries = useMemo(() => missedCards(data, now), [data, now]);
  return <MissedList entries={entries} data={data} now={now} />;
}
