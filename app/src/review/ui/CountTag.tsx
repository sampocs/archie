import { View } from "react-native";

import { Text } from "@/theme/components/Text";
import { fontFamily } from "@/theme/type";
import { useTheme } from "@/theme/useTheme";

// The tag's background: its signal colour at about 14% (hex alpha).
const TINT_ALPHA = "24";

type CountTagProps = { label: string; signal: "gotIt" | "missed"; testID?: string };

/** A small mono tag in a signal colour on its own tint: green "4 due", red "missed 2×". */
export function CountTag({ label, signal, testID }: CountTagProps) {
  const theme = useTheme();
  const color = theme.signals[signal];

  return (
    <View
      testID={testID}
      style={{
        backgroundColor: `${color}${TINT_ALPHA}`,
        borderRadius: 6,
        paddingHorizontal: 6,
        paddingVertical: 2,
      }}
    >
      <Text style={{ fontFamily: fontFamily.mono, fontSize: 10.5, color }}>{label}</Text>
    </View>
  );
}
