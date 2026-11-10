import { inArray } from "drizzle-orm";
import { useLiveQuery } from "drizzle-orm/expo-sqlite";
import * as Network from "expo-network";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Pressable, ScrollView, StyleSheet, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useSession } from "@/auth/session";
import { dropCard } from "@/db/actions";
import { db } from "@/db/client";
import * as schema from "@/db/schema";
import type { ReviewData } from "@/review/eligibility";
import { scheduleReminders } from "@/review/reminderScheduler";
import { buildSession } from "@/review/session";
import { AnswerBox } from "@/review/session/AnswerBox";
import { CareSheet } from "@/review/session/CareSheet";
import { DoneView } from "@/review/session/DoneView";
import { GradedCard, GradingCard } from "@/review/session/GradedCard";
import { QuestionCard } from "@/review/session/QuestionCard";
import { SelfGradeCard } from "@/review/session/SelfGradeCard";
import { appendTranscript, isOffline, micVisible, nextLiveIndex, sessionModeOf } from "@/review/sessionFlow";
import { gradedCount, tallyOf, type TallyEntry } from "@/review/tally";
import type { CardRow, ReviewGrade } from "@/review/types";
import { useGrader } from "@/review/useGrader";
import { useRecorder } from "@/review/useRecorder";
import { readReviewData, useReviewData } from "@/review/useReviewData";
import { requestSync } from "@/sync/useSync";
import { Button } from "@/theme/components/Button";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { haptic } from "@/ui/haptics";
import { Toast } from "@/ui/Toast";

const PROGRESS_BAR_HEIGHT = 3;

/**
 * A review session. `mode`: due | ahead | topic | source | take | card | quiz | shuffle | missed (unknown → due); `id`:
 * the topic, source, take or card.
 */
export default function ReviewSessionScreen() {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const params = useLocalSearchParams<{ mode?: string; id?: string }>();
  const { sessionKey } = useSession();
  const data = useReviewData();
  const online = !isOffline(Network.useNetworkState());

  // The card list is fixed when the session opens, from one synchronous read: the live queries arrive one table at a
  // time, and a list built from a half-loaded snapshot (cards without their sources) would come out empty.
  const [startedAt] = useState(() => new Date());
  const [session] = useState(() =>
    buildSession(readReviewData(db), sessionModeOf(params.mode), params.id ?? null, startedAt),
  );
  const ids = useMemo(() => session.map(({ card }) => card.id), [session]);

  // Each card's live row (deleted ones included), so a care rewrite shows and a card deleted meanwhile is skipped.
  const { data: liveRows, updatedAt } = useLiveQuery(
    db.select().from(schema.cards).where(inArray(schema.cards.id, ids)),
  );
  const liveById = useMemo(() => new Map(liveRows.map((row) => [row.id, row])), [liveRows]);
  const isLive = useCallback(
    (id: string) => {
      // Until the first read lands, the session's own fresh copy stands in.
      if (updatedAt === undefined) return true;
      const row = liveById.get(id);
      return row !== undefined && row.deletedAt === null;
    },
    [liveById, updatedAt],
  );

  const [index, setIndex] = useState(0);
  const [entries, setEntries] = useState<TallyEntry[]>([]);
  const [toast, setToast] = useState<string | null>(null);
  const hideToast = useCallback(() => setToast(null), []);
  const tally = useMemo(() => tallyOf(entries), [entries]);
  const done = ids.length > 0 && index >= ids.length;

  const current = session[index];
  const currentId = current?.card.id;
  const handled = entries.some((entry) => entry.cardId === currentId);
  // A row deleted mid-review still renders from the session's copy, so a graded card doesn't vanish under the user.
  const live = currentId ? liveById.get(currentId) : undefined;
  const card = live && live.deletedAt === null ? live : current?.card;

  // Reminders are replanned once per session, when it ends with something reviewed (Done, or ✕ after a review).
  const remindersPlanned = useRef(false);
  const planReminders = useCallback(() => {
    if (remindersPlanned.current) return;
    remindersPlanned.current = true;
    void scheduleReminders(db, { askPermission: true });
  }, []);
  useEffect(() => {
    if (done) planReminders();
  }, [done, planReminders]);

  // A card deleted elsewhere (a sync, the item page) before it was answered is skipped.
  useEffect(() => {
    if (currentId && !handled && !isLive(currentId)) setIndex(nextLiveIndex(ids, index, isLive));
  }, [currentId, handled, ids, index, isLive]);

  const onGraded = useCallback((cardId: string, grade: ReviewGrade) => {
    setEntries((previous) => [...previous, { cardId, outcome: grade }]);
  }, []);

  function next(): void {
    haptic("light");
    setIndex(nextLiveIndex(ids, index + 1, isLive));
  }

  function drop(cardId: string): void {
    dropCard(db, cardId);
    requestSync();
    haptic("light");
    setEntries((previous) => [...previous, { cardId, outcome: "dropped" }]);
    setIndex(nextLiveIndex(ids, index + 1, isLive));
  }

  // ✕ keeps whatever was graded: every grade was written when it was made.
  function close(): void {
    if (gradedCount(tally) > 0) planReminders();
    router.back();
  }

  return (
    <View style={[styles.root, { backgroundColor: theme.colors.bg }]}>
      <View style={{ paddingTop: insets.top }}>
        <View style={[styles.header, { paddingHorizontal: theme.spacing.gutterText }]}>
          <Pressable
            testID="review-close"
            accessibilityRole="button"
            accessibilityLabel="End review"
            onPress={close}
            hitSlop={12}
          >
            <Text variant="headline" tone="ink2" style={{ fontSize: 20 }}>
              ✕
            </Text>
          </Pressable>
          {ids.length > 0 && !done ? (
            <Text testID="review-progress" variant="monoLabel" tone="ink3">
              {`${index + 1} of ${ids.length}`}
            </Text>
          ) : null}
        </View>
        {ids.length > 0 && !done ? (
          <View
            style={[
              styles.bar,
              { backgroundColor: theme.colors.line, marginHorizontal: theme.spacing.gutterText },
            ]}
          >
            <View
              style={{ height: "100%", width: `${(index / ids.length) * 100}%`, backgroundColor: theme.colors.chrome }}
            />
          </View>
        ) : null}
      </View>
      {/* Keeps the answer box above the keyboard as it grows. */}
      <ScrollView
        keyboardShouldPersistTaps="handled"
        automaticallyAdjustKeyboardInsets
        contentContainerStyle={{
          flexGrow: 1,
          padding: theme.spacing.gutterCards,
          paddingBottom: insets.bottom + theme.spacing.gutterCards,
          gap: theme.spacing.lg,
        }}
      >
        {ids.length === 0 ? (
          <Empty onBack={router.back} />
        ) : done ? (
          <DoneView tally={tally} startedAt={startedAt} data={data} />
        ) : card && current ? (
          <CardStep
            key={card.id}
            card={card}
            wasDue={current.wasDue}
            data={data}
            sessionKey={sessionKey}
            online={online}
            onGraded={onGraded}
            onNext={next}
            onDrop={() => drop(card.id)}
            onToast={setToast}
          />
        ) : null}
      </ScrollView>
      {toast ? <Toast message={toast} onHide={hideToast} /> : null}
    </View>
  );
}

type CardStepProps = {
  card: CardRow;
  wasDue: boolean;
  data: ReviewData;
  sessionKey: string | null;
  online: boolean;
  onGraded: (cardId: string, grade: ReviewGrade) => void;
  onNext: () => void;
  onDrop: () => void;
  onToast: (message: string) => void;
};

// One card, from question to Next; remounted per card (its `key`), so the answer, grade and recorder start fresh.
function CardStep({ card, wasDue, data, sessionKey, online, onGraded, onNext, onDrop, onToast }: CardStepProps) {
  const theme = useTheme();
  const [answer, setAnswer] = useState("");
  const [careOpen, setCareOpen] = useState(false);
  const { phase, submit, selfGrade, knewIt } = useGrader({ card, wasDue, sessionKey, onGraded });
  const recorder = useRecorder({
    cardId: card.id,
    sessionKey,
    onText: (text) => setAnswer((typed) => appendTranscript(typed, text)),
    onError: onToast,
  });
  const showNext = phase.kind === "graded" || (phase.kind === "selfGrade" && phase.chosen !== null);

  return (
    <View style={{ gap: theme.spacing.lg }}>
      <QuestionCard card={card} data={data} />
      {phase.kind === "answering" ? (
        <AnswerBox
          value={answer}
          onChangeText={setAnswer}
          onSubmit={() => void submit(answer)}
          onDrop={onDrop}
          showMic={micVisible(online, recorder.status)}
          micStatus={recorder.status}
          onMic={recorder.toggle}
        />
      ) : null}
      {phase.kind === "grading" ? <GradingCard answer={phase.answer} acceptedAnswer={card.answer} acceptedDetail={card.detail} /> : null}
      {phase.kind === "graded" ? (
        <GradedCard
          answer={phase.answer}
          grade={phase.grade}
          missing={phase.missing}
          acceptedAnswer={card.answer}
          acceptedDetail={card.detail}
          canKnewIt={phase.replaced !== null}
          onKnewIt={knewIt}
          online={online}
          onCare={() => setCareOpen(true)}
        />
      ) : null}
      {phase.kind === "selfGrade" ? (
        <SelfGradeCard
          answer={phase.answer}
          acceptedAnswer={card.answer}
          acceptedDetail={card.detail}
          reason={phase.reason}
          chosen={phase.chosen}
          onGrade={selfGrade}
        />
      ) : null}
      {showNext ? <Button testID="review-next" label="Next →" onPress={onNext} /> : null}
      <CareSheet cardId={card.id} sessionKey={sessionKey} visible={careOpen} onClose={() => setCareOpen(false)} />
    </View>
  );
}

function Empty({ onBack }: { onBack: () => void }) {
  const theme = useTheme();
  return (
    <View testID="review-empty" style={[styles.empty, { gap: theme.spacing.lg }]}>
      <Text variant="headline">Nothing to review.</Text>
      <View style={{ alignSelf: "stretch" }}>
        <Button testID="review-empty-back" label="Back" variant="secondary" onPress={onBack} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingVertical: 12 },
  bar: { height: PROGRESS_BAR_HEIGHT, borderRadius: 2, overflow: "hidden" },
  empty: { flex: 1, alignItems: "center", justifyContent: "center" },
});
