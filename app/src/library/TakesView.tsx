import { View } from "react-native";

import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";

/** Library's Takes mode. Piece 3 adds the Write a take button and the list; until then only the empty state shows. */
export function TakesView() {
  const theme = useTheme();

  return (
    <View style={{ alignItems: "center", paddingVertical: theme.spacing.xl }}>
      <Text testID="takes-empty" tone="ink2">
        Things you think, in your own words
      </Text>
    </View>
  );
}
