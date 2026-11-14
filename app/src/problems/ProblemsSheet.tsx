import { View } from "react-native";

import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { BottomSheet } from "@/ui/BottomSheet";

import { agoLabel, type Problem } from "./problems";

type ProblemsSheetProps = { problems: Problem[]; now: Date; visible: boolean; onClose: () => void };

/** Each problem with what it is, the detail, and how long it has been going on. */
export function ProblemsSheet({ problems, now, visible, onClose }: ProblemsSheetProps) {
  const theme = useTheme();

  return (
    <BottomSheet visible={visible} onClose={onClose} testID="problems-sheet">
      <Text variant="headline">Needs a look</Text>
      {problems.map((problem) => (
        <View key={`${problem.kind}:${problem.key}`} style={{ gap: theme.spacing.xs }}>
          <Text>{problem.title}</Text>
          <Text variant="secondary" tone="ink2">
            {problem.detail}
          </Text>
          <Text variant="secondary" tone="ink3">
            {`since ${agoLabel(problem.since, now)}`}
          </Text>
        </View>
      ))}
    </BottomSheet>
  );
}
