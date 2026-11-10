import { useCallback, type ReactNode } from "react";
import * as Network from "expo-network";
import { useFocusEffect, useRouter } from "expo-router";
import { Pressable, View } from "react-native";
import Animated, { FadeIn, FadeOut, FadeOutUp, LinearTransition, useReducedMotion } from "react-native-reanimated";

import { storyCountLabel } from "@/brief/brief";
import { BriefPreviewCard } from "@/brief/BriefPreviewCard";
import { db } from "@/db/client";
import { requestNewsQuiz, skipNote } from "@/db/actions";
import { RefresherCard } from "@/notes/RefresherCard";
import { upNext } from "@/library/visibility";
import { useLibraryData } from "@/library/useLibraryData";
import { cardsWord } from "@/review/labels";
import { weekStartFor } from "@/review/newsQuiz";
import { ReviewStartCard } from "@/review/ui/ReviewStartCard";
import { useReviewData } from "@/review/useReviewData";
import { requestSync } from "@/sync/useSync";
import { Screen } from "@/theme/components/Screen";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { DayDoneCard } from "@/today/DayDoneCard";
import { DoneRow } from "@/today/DoneRow";
import { NewsQuizCard } from "@/today/NewsQuizCard";
import { localDate, todayDate } from "@/today/todayLabels";
import { notesWord, type TaskKind } from "@/today/todayTasks";
import { useTodayCelebration } from "@/today/useTodayCelebration";
import { useTodayTasks } from "@/today/useTodayTasks";
import { GroupedList } from "@/ui/GroupedList";
import { QueuedPrimerRow } from "@/ui/QueuedPrimerRow";
import { SourceRow } from "@/ui/SourceRow";
import { haptic } from "@/ui/haptics";
import { useNow } from "@/ui/useNow";

const UP_NEXT_COUNT = 3;
// A finished task's card eases into its done row while the cards below close up.
const SLOT_LAYOUT_MS = 450;
const CARD_OUT_MS = 200;
const ROW_IN_MS = 250;
const ROW_IN_DELAY_MS = 150;
const ROWS_OUT_MS = 350;

// The week already asked for this app run: the quiz is requested at most once per week per run.
let requestedWeek: string | null = null;

export default function TodayScreen() {
  const theme = useTheme();
  const router = useRouter();
  const now = useNow();
  const data = useLibraryData();
  const reviewData = useReviewData();
  // On a Sunday, ask the server for the week's news quiz once per run; it is only asked for when online.
  useFocusEffect(
    useCallback(() => {
      const weekStart = weekStartFor(new Date());
      if (weekStart === null || weekStart === requestedWeek) return;

      void Network.getNetworkStateAsync().then((state) => {
        if (!state.isConnected || weekStart === requestedWeek) return;
        requestedWeek = weekStart;
        requestNewsQuiz(db, weekStart);
        requestSync();
      });
    }, []),
  );

  // Up next is the combined queue: queued sources and queued primers.
  const queued = upNext(data.sources, now);
  const upNextItems = queued.slice(0, UP_NEXT_COUNT);
  const view = useTodayTasks(data.sources, reviewData, now);
  const celebration = useTodayCelebration(view.tasks, localDate(now));
  const { tasks } = celebration;
  const reduceMotion = useReducedMotion();
  const motion = celebration.settled && !reduceMotion;
  const isEmpty =
    upNextItems.length === 0 && tasks.review === null && tasks.notes === null && tasks.quiz === null && tasks.brief === null;

  const dateLabel = (
    <Text testID="today-date" variant="monoLabel" tone="ink3">
      {todayDate(now)}
    </Text>
  );

  // Each task sits in its own animated slot; swapping a card for its done row (or the rows for the day card) eases.
  const slot = (key: string, kind: TaskKind | null, content: ReactNode) => {
    const isRow = key.endsWith("-done");
    const freshRow = isRow && kind !== null && celebration.isFresh(kind);
    return (
      <Animated.View
        key={key}
        layout={motion ? LinearTransition.duration(SLOT_LAYOUT_MS) : undefined}
        entering={motion && freshRow ? FadeIn.duration(ROW_IN_MS).delay(ROW_IN_DELAY_MS) : undefined}
        exiting={motion ? (isRow ? FadeOutUp.duration(ROWS_OUT_MS) : FadeOut.duration(CARD_OUT_MS)) : undefined}
      >
        {content}
      </Animated.View>
    );
  };

  const taskSlots = celebration.showDayCard
    ? [
        slot(
          "day-card",
          null,
          <DayDoneCard backTomorrow={view.backTomorrow} chips={view.chips} celebrate={celebration.celebrateDay} />,
        ),
      ]
    : [reviewSlot(), notesSlot(), quizSlot(), briefSlot()].filter((entry) => entry !== null);

  function reviewSlot() {
    const review = tasks.review;
    if (review === null) return null;
    if (review.status === "done") {
      return slot(
        "review-done",
        "review",
        <DoneRow
          testID="today-review-done"
          title={`${cardsWord(review.reviewed)} reviewed`}
          detail={review.next ? `next ${review.next}` : null}
          link="More ›"
          onPress={() => router.push("/(tabs)/review")}
          celebrate={celebration.isFresh("review")}
        />,
      );
    }
    return slot(
      "review-card",
      "review",
      <ReviewStartCard
        testID="today-review"
        count={review.due}
        headerDetail={review.status === "pending" ? `about ${review.minutes} min` : `${review.reviewed} of ${review.total} done`}
        progress={review.status === "inProgress" ? { reviewed: review.reviewed, total: review.total } : undefined}
        onPress={() => router.push({ pathname: "/review/session", params: { mode: "due" } })}
      />,
    );
  }

  function notesSlot() {
    const notes = tasks.notes;
    if (notes === null) return null;
    if (notes.status === "done") {
      const next = notes.next;
      return slot(
        "notes-done",
        "notes",
        <DoneRow
          testID="today-refresher-done"
          title={`${notesWord(notes.refreshed)} refreshed`}
          detail={next ? `next: ${next.title ?? next.url}` : null}
          onPress={next ? () => router.push({ pathname: "/source/[id]", params: { id: next.id } }) : undefined}
          celebrate={celebration.isFresh("notes")}
        />,
      );
    }
    return slot(
      "notes-card",
      "notes",
      <RefresherCard
        state={notes.refresher}
        onOpen={(id) => router.push({ pathname: "/source/[id]", params: { id } })}
        onSkip={(id) => {
          skipNote(db, id);
          haptic("light");
          requestSync();
        }}
      />,
    );
  }

  function quizSlot() {
    const quiz = tasks.quiz;
    if (quiz === null) return null;
    if (quiz.status === "done") {
      return slot(
        "quiz-done",
        "quiz",
        <DoneRow
          testID="today-quiz-done"
          title="News quiz"
          detail={`${quiz.gotIt} of ${quiz.answered} got it`}
          celebrate={celebration.isFresh("quiz")}
        />,
      );
    }
    return slot(
      "quiz-card",
      "quiz",
      <NewsQuizCard
        count={quiz.count}
        until={quiz.until}
        onPress={() => router.push({ pathname: "/review/session", params: { mode: "quiz" } })}
      />,
    );
  }

  function briefSlot() {
    const brief = tasks.brief;
    if (brief === null) return null;
    if (brief.status === "done") {
      return slot(
        "brief-done",
        "brief",
        <DoneRow
          testID="today-brief-done"
          title="Brief read"
          detail={storyCountLabel(brief.stories)}
          link="Open ›"
          onPress={() => router.push("/brief")}
          celebrate={celebration.isFresh("brief")}
        />,
      );
    }
    return slot("brief-card", "brief", <BriefPreviewCard state={brief.brief} />);
  }

  return (
    <Screen title="Today" headerRight={dateLabel}>
      {taskSlots.length > 0 ? <View style={{ gap: theme.spacing.lg }}>{taskSlots}</View> : null}

      {upNextItems.length > 0 ? (
        <Animated.View layout={motion ? LinearTransition.duration(SLOT_LAYOUT_MS) : undefined}>
          <GroupedList
            title="Up next"
            right={
              <Pressable
                testID="today-see-all"
                onPress={() => router.push({
                    pathname: "/(tabs)/library",
                    params: { filter: "queued", at: String(Date.now()) },
                  })}
                hitSlop={8}
              >
                <Text variant="secondary" tone="ink2">
                  {`See all ${queued.length} ›`}
                </Text>
              </Pressable>
            }
          >
            {upNextItems.map((entry, index) =>
              entry.kind === "source" ? (
                <SourceRow key={entry.key} source={entry.source} testID={`up-next-${index}`} />
              ) : (
                <QueuedPrimerRow key={entry.key} source={entry.source} testID={`up-next-${index}`} />
              ),
            )}
          </GroupedList>
        </Animated.View>
      ) : null}

      {isEmpty ? (
        <Text testID="today-empty" tone="ink2">
          Nothing waiting. Add a link with ＋ in Library, or share one to Archie.
        </Text>
      ) : null}
    </Screen>
  );
}
