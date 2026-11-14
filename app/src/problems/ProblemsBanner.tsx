import { Pressable, View } from "react-native";

import { Card } from "@/theme/components/Card";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";

import { bannerText } from "./problems";

/** A quiet line at the top of Today when something needs a look; tapping it opens the list. */
export function ProblemsBanner({ count, onPress }: { count: number; onPress: () => void }) {
  const theme = useTheme();

  return (
    <Pressable testID="problems-banner" accessibilityRole="button" onPress={onPress}>
      <Card style={{ flexDirection: "row", alignItems: "center", gap: theme.spacing.md, paddingVertical: theme.spacing.md }}>
        {/* The warning signal color, as a dot: amber, not red, since nothing here is an emergency. */}
        <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: theme.signals.partly }} />
        <Text style={{ flex: 1 }}>{bannerText(count)}</Text>
        <Text tone="ink3">›</Text>
      </Card>
    </Pressable>
  );
}
