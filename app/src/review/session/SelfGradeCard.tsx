import { Pressable, View } from "react-native";

import { GRADE_LABELS } from "@/review/labels";
import type { ReviewGrade } from "@/review/types";
import { GRADE_SIGNALS } from "@/review/ui/VerdictPill";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";

import { AcceptedAnswer, Labelled, ResultCard } from "./GradedCard";

const GRADES: readonly ReviewGrade[] = ["got_it", "partly", "missed"];
const GRADE_BUTTON_HEIGHT = 46;

type SelfGradeCardProps = {
  answer: string;
  acceptedAnswer: string;
  acceptedDetail: string;
  reason: string | null;
  // The grade already chosen; the buttons lock once one is.
  chosen: ReviewGrade | null;
  onGrade: (grade: ReviewGrade) => void;
};

/** No model verdict (mock 02): compare with the answer and pick a grade yourself. */
export function SelfGradeCard({ answer, acceptedAnswer, acceptedDetail, reason, chosen, onGrade }: SelfGradeCardProps) {
  const theme = useTheme();

  return (
    <View style={{ gap: theme.spacing.md }}>
      <ResultCard>
        {answer.trim() === "" ? null : (
          <Labelled label="You said">
            <Text testID="review-you-said" tone="ink2">
              {answer.trim()}
            </Text>
          </Labelled>
        )}
        <AcceptedAnswer answer={acceptedAnswer} detail={acceptedDetail} />
        <View style={{ flexDirection: "row", gap: theme.spacing.sm }}>
          {GRADES.map((grade) => (
            <GradeButton
              key={grade}
              grade={grade}
              state={chosen === null ? "open" : chosen === grade ? "chosen" : "other"}
              onPress={() => onGrade(grade)}
            />
          ))}
        </View>
      </ResultCard>
      {reason ? (
        <Text testID="review-self-reason" variant="monoLabel" tone="ink3" style={{ textAlign: "center" }}>
          {reason}
        </Text>
      ) : null}
    </View>
  );
}

type GradeButtonProps = { grade: ReviewGrade; state: "open" | "chosen" | "other"; onPress: () => void };

function GradeButton({ grade, state, onPress }: GradeButtonProps) {
  const theme = useTheme();
  const color = theme.signals[GRADE_SIGNALS[grade]];

  return (
    <Pressable
      testID={`self-grade-${grade}`}
      accessibilityRole="button"
      accessibilityState={{ selected: state === "chosen", disabled: state !== "open" }}
      onPress={onPress}
      disabled={state !== "open"}
      style={({ pressed }) => ({
        flex: 1,
        height: GRADE_BUTTON_HEIGHT,
        alignItems: "center",
        justifyContent: "center",
        borderRadius: theme.radii.chip,
        borderWidth: 1.5,
        borderColor: color,
        backgroundColor: state === "chosen" ? color : `${color}1F`,
        opacity: state === "other" ? 0.4 : 1,
        transform: [{ scale: pressed ? 0.97 : 1 }],
      })}
    >
      <Text variant="headline" style={{ color: state === "chosen" ? theme.colors.surface : color }}>
        {GRADE_LABELS[grade]}
      </Text>
    </Pressable>
  );
}
