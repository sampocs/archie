import { View } from "react-native";

import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";

type DetailBulletsProps = {
  lines: string[];
  // The line text's tone; the bullet itself is always ink3.
  tone: "ink2" | "ink3";
  testID?: string;
};

/** A card's detail lines as bullets (nothing when there are none). */
export function DetailBullets({ lines, tone, testID }: DetailBulletsProps) {
  const theme = useTheme();
  if (lines.length === 0) return null;
  return (
    <View style={{ gap: theme.spacing.xs }}>
      {lines.map((line, index) => (
        <View key={index} style={{ flexDirection: "row", gap: theme.spacing.sm }}>
          <Text variant="secondary" tone="ink3">
            •
          </Text>
          <Text testID={testID} variant="secondary" tone={tone} style={{ flex: 1 }}>
            {line}
          </Text>
        </View>
      ))}
    </View>
  );
}
