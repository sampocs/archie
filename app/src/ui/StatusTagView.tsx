import { View } from "react-native";

import type { StatusTag } from "@/library/visibility";
import { Text } from "@/theme/components/Text";
import { fontFamily } from "@/theme/type";
import { useTheme } from "@/theme/useTheme";

type StatusTagViewProps = { tag: StatusTag; testID?: string };

export function StatusTagView({ tag, testID }: StatusTagViewProps) {
  const theme = useTheme();

  if (tag === "Unread") {
    return (
      <Text testID={testID} variant="secondary" style={{ fontFamily: fontFamily.semibold }}>
        {tag}
      </Text>
    );
  }
  if (tag === "Processing") {
    return (
      <Text testID={testID} variant="secondary" tone="ink3">
        {tag}
      </Text>
    );
  }
  if (tag === "Failed") {
    return (
      <Text testID={testID} variant="secondary" style={{ color: theme.signals.missed }}>
        {tag}
      </Text>
    );
  }
  return (
    <View
      testID={testID}
      style={{
        backgroundColor: theme.colors.press,
        borderRadius: theme.radii.chipSmall,
        paddingHorizontal: theme.spacing.sm,
        paddingVertical: theme.spacing.xs,
      }}
    >
      <Text variant="monoLabel" tone="ink2">
        {tag}
      </Text>
    </View>
  );
}
