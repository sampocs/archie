import { View } from "react-native";

import { Text } from "@/theme/components/Text";

// On the green review card the header is white, a little softened.
export const ON_GREEN_SOFT = "rgba(255,255,255,0.85)";

type CardHeaderProps = { label: string; detail?: string; onGreen?: boolean; testID?: string };

/** A Today task card's top line: a small uppercase label on the left and a mono detail on the right. */
export function CardHeader({ label, detail, onGreen, testID }: CardHeaderProps) {
  const color = onGreen ? { color: ON_GREEN_SOFT } : null;
  return (
    <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "baseline", gap: 8 }}>
      <Text variant="kicker" tone="ink2" style={color}>
        {label}
      </Text>
      {detail ? (
        <Text testID={testID} variant="monoLabel" tone="ink3" numberOfLines={1} style={[{ flexShrink: 1 }, color]}>
          {detail}
        </Text>
      ) : null}
    </View>
  );
}
