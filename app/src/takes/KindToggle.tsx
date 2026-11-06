import { Pressable, StyleSheet, View } from "react-native";

import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { haptic } from "@/ui/haptics";

import { TAKE_KIND_LABELS, type TakeKind } from "./takes";

const KINDS: readonly TakeKind[] = ["opinion", "talking_point"];

/** Two-segment Opinion | Talking point control, styled like the Library mode switch. */
export function KindToggle({
  value,
  onChange,
  testIDPrefix,
}: {
  value: TakeKind;
  onChange: (kind: TakeKind) => void;
  testIDPrefix: string;
}) {
  const theme = useTheme();

  return (
    <View style={{ flexDirection: "row", backgroundColor: theme.colors.press, borderRadius: 10, padding: 2 }}>
      {KINDS.map((kind) => (
        <Pressable
          key={kind}
          testID={`${testIDPrefix}-${kind}`}
          onPress={() => {
            if (kind === value) return;
            haptic("selection");
            onChange(kind);
          }}
          style={[
            {
              flex: 1,
              alignItems: "center",
              paddingVertical: theme.spacing.sm,
              borderRadius: 8,
              backgroundColor: value === kind ? theme.colors.surface : "transparent",
            },
            value === kind && theme.scheme === "light" && styles.shadow,
          ]}
        >
          <Text variant="secondary" tone={value === kind ? "ink" : "ink3"}>
            {TAKE_KIND_LABELS[kind]}
          </Text>
        </Pressable>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  shadow: { shadowColor: "#0E0E0C", shadowOpacity: 0.1, shadowRadius: 2, shadowOffset: { width: 0, height: 1 } },
});
