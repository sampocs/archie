import { View } from "react-native";

import { GRADE_LABELS } from "@/review/labels";
import type { ReviewGrade } from "@/review/types";
import { Text } from "@/theme/components/Text";
import type { Signal } from "@/theme/tokens";
import { useTheme } from "@/theme/useTheme";

const GRADE_SIGNALS: Record<ReviewGrade, Signal> = { got_it: "gotIt", partly: "partly", missed: "missed" };

/** The grade label on a pill tinted with its signal colour. */
export function VerdictPill({ grade }: { grade: ReviewGrade }) {
  const theme = useTheme();
  const color = theme.signals[GRADE_SIGNALS[grade]];

  return (
    <View
      testID="review-verdict"
      style={{
        alignSelf: "flex-start",
        backgroundColor: `${color}26`,
        borderRadius: theme.radii.chip,
        paddingHorizontal: theme.spacing.md,
        paddingVertical: theme.spacing.xs,
      }}
    >
      <Text variant="headline" style={{ color }}>
        {GRADE_LABELS[grade]}
      </Text>
    </View>
  );
}
