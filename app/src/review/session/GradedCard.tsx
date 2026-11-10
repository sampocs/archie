import { type ReactNode, useEffect, useRef } from "react";
import { Animated, Pressable, StyleSheet, View } from "react-native";

import { detailLines } from "@/review/detail";
import type { ReviewGrade } from "@/review/types";
import { DetailBullets } from "@/review/ui/DetailBullets";
import { GRADE_SIGNALS, VerdictPill } from "@/review/ui/VerdictPill";
import { Card } from "@/theme/components/Card";
import { Text } from "@/theme/components/Text";
import { fontFamily } from "@/theme/type";
import { useTheme } from "@/theme/useTheme";

const PULSE_MS = 600;

type GradedCardProps = {
  answer: string;
  grade: ReviewGrade;
  missing: string;
  acceptedAnswer: string;
  acceptedDetail: string;
  // "I actually knew it" shows under Partly and Missed until it is used.
  canKnewIt: boolean;
  onKnewIt: () => void;
  // Rewriting the answer needs the server.
  online: boolean;
  onCare: () => void;
};

/** The answer box turned into the graded card (mock 01), with the two follow-ups under it. */
export function GradedCard(props: GradedCardProps) {
  const theme = useTheme();
  const color = theme.signals[GRADE_SIGNALS[props.grade]];

  return (
    <View style={{ gap: theme.spacing.md }}>
      <ResultCard>
        <Labelled label="You said">
          <Text testID="review-you-said" tone="ink2">
            {props.answer.trim()}
          </Text>
        </Labelled>
        <VerdictPill grade={props.grade} />
        {props.grade !== "got_it" && props.missing !== "" ? (
          <Text
            testID="review-missing"
            style={{
              backgroundColor: `${color}1A`,
              borderRadius: theme.radii.chip,
              paddingHorizontal: theme.spacing.md,
              paddingVertical: 10,
              overflow: "hidden",
            }}
          >
            {props.missing}
          </Text>
        ) : null}
        <AcceptedAnswer answer={props.acceptedAnswer} detail={props.acceptedDetail} />
      </ResultCard>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: theme.spacing.sm }}>
        {props.canKnewIt ? (
          <Chip testID="review-knew-it" label="I actually knew it" onPress={props.onKnewIt} />
        ) : null}
        <Chip testID="review-care" label="What I care about…" onPress={props.onCare} disabled={!props.online}>
          {props.online ? null : (
            <Text testID="review-care-offline" variant="secondary" tone="ink3">
              Needs a connection
            </Text>
          )}
        </Chip>
      </View>
    </View>
  );
}

/** While the grader thinks: what you said, the answer, and a pulsing "Grading…". */
export function GradingCard({
  answer,
  acceptedAnswer,
  acceptedDetail,
}: {
  answer: string;
  acceptedAnswer: string;
  acceptedDetail: string;
}) {
  const opacity = useRef(new Animated.Value(1)).current;

  useEffect(() => {
    const pulse = Animated.loop(
      Animated.sequence([
        Animated.timing(opacity, { toValue: 0.35, duration: PULSE_MS, useNativeDriver: true }),
        Animated.timing(opacity, { toValue: 1, duration: PULSE_MS, useNativeDriver: true }),
      ]),
    );
    pulse.start();
    return () => pulse.stop();
  }, [opacity]);

  return (
    <ResultCard>
      <Labelled label="You said">
        <Text testID="review-you-said" tone="ink2">
          {answer.trim()}
        </Text>
      </Labelled>
      <Animated.View style={{ opacity }}>
        <Text testID="review-grading" variant="monoLabel" tone="ink3">
          Grading…
        </Text>
      </Animated.View>
      <AcceptedAnswer answer={acceptedAnswer} detail={acceptedDetail} />
    </ResultCard>
  );
}

/** The white card a result sits in (the answer box's shape). */
export function ResultCard({ children }: { children: ReactNode }) {
  const theme = useTheme();
  return <Card style={{ borderRadius: theme.radii.textBox, gap: theme.spacing.md }}>{children}</Card>;
}

/** A mono label over its content ("YOU SAID", "ANSWER"). */
export function Labelled({ label, children }: { label: string; children: ReactNode }) {
  const theme = useTheme();
  return (
    <View style={{ gap: theme.spacing.xs }}>
      <Text variant="monoLabel" tone="ink3">
        {label}
      </Text>
      {children}
    </View>
  );
}

/** The card's own answer; with detail it is set semibold and the detail lines follow under a hairline. */
export function AcceptedAnswer({ answer, detail }: { answer: string; detail: string }) {
  const theme = useTheme();
  const lines = detailLines(detail);
  if (lines.length === 0) {
    return (
      <Labelled label="Answer">
        <Text testID="review-accepted-answer" variant="readingBody">
          {answer}
        </Text>
      </Labelled>
    );
  }
  return (
    <Labelled label="Answer">
      <Text testID="review-accepted-answer" variant="readingBody" style={{ fontFamily: fontFamily.semibold }}>
        {answer}
      </Text>
      <View
        style={{
          height: StyleSheet.hairlineWidth,
          backgroundColor: theme.colors.line,
          marginVertical: theme.spacing.xs,
        }}
      />
      <DetailBullets testID="review-accepted-detail" lines={lines} tone="ink2" />
    </Labelled>
  );
}

type ChipProps = { testID: string; label: string; onPress: () => void; disabled?: boolean; children?: ReactNode };

function Chip({ testID, label, onPress, disabled = false, children }: ChipProps) {
  const theme = useTheme();
  return (
    <Pressable
      testID={testID}
      accessibilityRole="button"
      accessibilityState={{ disabled }}
      onPress={onPress}
      disabled={disabled}
      style={({ pressed }) => ({
        flexDirection: "row",
        alignItems: "center",
        gap: theme.spacing.sm,
        backgroundColor: pressed ? theme.colors.press : theme.colors.surface,
        borderColor: theme.colors.line,
        borderWidth: 1,
        borderRadius: theme.radii.chipSmall,
        paddingHorizontal: theme.spacing.md,
        paddingVertical: theme.spacing.sm,
      })}
    >
      <Text variant="secondary" tone={disabled ? "ink3" : "ink2"}>
        {label}
      </Text>
      {children}
    </Pressable>
  );
}
