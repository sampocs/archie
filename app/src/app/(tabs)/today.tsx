import { Ionicons } from "@expo/vector-icons";
import * as Clipboard from "expo-clipboard";
import { useLiveQuery } from "drizzle-orm/expo-sqlite";
import { useCallback, useEffect, useState } from "react";
import * as Network from "expo-network";
import { useFocusEffect, useRouter } from "expo-router";
import { Pressable, View } from "react-native";

import { newsletterAddressFrom } from "@/account/newsletterAddress";
import { apiFetch } from "@/api/client";
import { useSession } from "@/auth/session";
import { useSignOut } from "@/context/SignOutContext";
import { todayBrief } from "@/brief/brief";
import { BriefPreviewCard } from "@/brief/BriefPreviewCard";
import { db } from "@/db/client";
import * as schema from "@/db/schema";
import { requestNewsQuiz } from "@/db/actions";
import { upNext } from "@/library/visibility";
import { useLibraryData } from "@/library/useLibraryData";
import { quizOffer, weekStartFor } from "@/review/newsQuiz";
import { dueSummary, shortWeekday } from "@/review/summary";
import { ReviewStartCard } from "@/review/ui/ReviewStartCard";
import { useReviewData } from "@/review/useReviewData";
import { requestSync } from "@/sync/useSync";
import { Button } from "@/theme/components/Button";
import { Card } from "@/theme/components/Card";
import { Screen } from "@/theme/components/Screen";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { todayDate } from "@/today/todayLabels";
import { GroupedList } from "@/ui/GroupedList";
import { QueuedPrimerRow } from "@/ui/QueuedPrimerRow";
import { SourceRow } from "@/ui/SourceRow";
import { useNow } from "@/ui/useNow";

const UP_NEXT_COUNT = 3;

// The week already asked for this app run: the quiz is requested at most once per week per run.
let requestedWeek: string | null = null;

export default function TodayScreen() {
  const theme = useTheme();
  const router = useRouter();
  const now = useNow();
  const data = useLibraryData();
  const { data: briefs } = useLiveQuery(db.select().from(schema.briefs));
  const reviewData = useReviewData();
  const signOut = useSignOut();
  const session = useSession();
  const [sheetOpen, setSheetOpen] = useState(false);
  const [newsletterAddress, setNewsletterAddress] = useState<string | null>(
    null,
  );

  // Fetched each time the sheet opens; any failure just hides the row.
  useEffect(() => {
    if (!sheetOpen || session.status !== "signedIn") return;

    let cancelled = false;
    apiFetch("/me", { sessionKey: session.sessionKey })
      .then((me) => {
        if (!cancelled) setNewsletterAddress(newsletterAddressFrom(me));
      })
      .catch(() => {
        if (!cancelled) setNewsletterAddress(null);
      });
    return () => {
      cancelled = true;
    };
  }, [sheetOpen, session.status, session.sessionKey]);

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
  const brief = todayBrief(briefs, data.sources);
  const due = dueSummary(reviewData, now);
  const quiz = quizOffer(reviewData, now);
  const isEmpty = upNextItems.length === 0 && brief === null && due.count === 0 && quiz === null;

  const accountButton = (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        gap: theme.spacing.sm,
      }}
    >
      <Text testID="today-date" variant="monoLabel" tone="ink3">
        {todayDate(now)}
      </Text>
      <Pressable
        testID="account-button"
        accessibilityLabel="Account"
        hitSlop={12}
        onPress={() => setSheetOpen((open) => !open)}
      >
        <Ionicons
          name="person-circle-outline"
          size={28}
          color={theme.colors.ink2}
        />
      </Pressable>
    </View>
  );

  return (
    <Screen title="Today" headerRight={accountButton}>
      {/* Inline sheet rather than Alert, which Maestro can't drive reliably. */}
      {sheetOpen ? (
        <Card style={{ gap: theme.spacing.sm }}>
          {newsletterAddress ? (
            <>
              <Text variant="kicker" tone="ink2">
                Newsletter address
              </Text>
              <Text testID="newsletter-address" selectable>
                {newsletterAddress}
              </Text>
              <Button
                testID="newsletter-address-copy"
                label="Copy"
                variant="secondary"
                onPress={() => void Clipboard.setStringAsync(newsletterAddress)}
              />
            </>
          ) : null}
          <Button
            testID="removed-topics-link"
            label="Removed topics"
            variant="secondary"
            onPress={() => router.push("/settings/removed-topics")}
          />
          <Button
            testID="review-settings-link"
            label="Review reminder"
            variant="secondary"
            onPress={() => router.push("/settings/review")}
          />
          <Button
            testID="sign-out"
            label="Sign out"
            variant="secondary"
            onPress={signOut}
          />
        </Card>
      ) : null}

      {due.count > 0 ? (
        <ReviewStartCard
          testID="today-review"
          count={due.count}
          foundations={due.foundations}
          onPress={() => router.push({ pathname: "/review/session", params: { mode: "due" } })}
        />
      ) : null}

      {quiz ? (
        <Pressable
          testID="today-quiz"
          accessibilityRole="button"
          onPress={() => router.push({ pathname: "/review/session", params: { mode: "quiz" } })}
        >
          <Card style={{ gap: theme.spacing.xs }}>
            <Text variant="headline">This week's news quiz</Text>
            <Text variant="secondary" tone="ink2">
              {`${quiz.count} ${quiz.count === 1 ? "question" : "questions"} · from your briefs · until ${shortWeekday(quiz.until)}`}
            </Text>
          </Card>
        </Pressable>
      ) : null}

      {brief ? <BriefPreviewCard state={brief} /> : null}

      {upNextItems.length > 0 ? (
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
      ) : null}

      {isEmpty ? (
        <Text testID="today-empty" tone="ink2">
          Nothing waiting. Tap ＋ to add a link, or share one to Archie.
        </Text>
      ) : null}
    </Screen>
  );
}
