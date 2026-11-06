import { useRouter } from "expo-router";

import { cardsWord } from "@/review/labels";
import { aheadSummary, dayWord, dueSummary, nextReview } from "@/review/summary";
import { KeepGoing } from "@/review/ui/KeepGoing";
import { ReviewStartCard } from "@/review/ui/ReviewStartCard";
import { useReviewData } from "@/review/useReviewData";
import { Screen } from "@/theme/components/Screen";
import { Text } from "@/theme/components/Text";
import { useNow } from "@/ui/useNow";

export default function ReviewScreen() {
  const router = useRouter();
  const now = useNow();
  const data = useReviewData();
  const due = dueSummary(data, now);
  const ahead = aheadSummary(data, now);
  const next = nextReview(data, now);

  return (
    <Screen title="Review">
      {due.count > 0 ? (
        <ReviewStartCard
          testID="review-tab-start"
          count={due.count}
          foundations={due.foundations}
          onPress={() => router.push({ pathname: "/review/session", params: { mode: "due" } })}
        />
      ) : (
        <Text testID="review-caught-up" tone="ink2">
          {next
            ? `All caught up. ${cardsWord(next.count)} ${next.count === 1 ? "is" : "are"} due ${dayWord(next.at, now)}.`
            : "All caught up."}
        </Text>
      )}

      <KeepGoing
        aheadCount={ahead.count}
        aheadBy={ahead.by}
        onAhead={() => router.push({ pathname: "/review/session", params: { mode: "ahead" } })}
        onTopic={() => router.push("/review/topics")}
      />
    </Screen>
  );
}
