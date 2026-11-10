import { Pressable, PressableProps, StyleSheet } from "react-native";

import { useTheme } from "../useTheme";
import { Text } from "./Text";

type ButtonProps = Omit<PressableProps, "children" | "style"> & {
  label: string;
  // Primary is chrome (graphite); secondary is a white surface card (card shadow), same height and radius.
  variant?: "primary" | "secondary";
  // Overrides the label's tone, e.g. a signal color for a done state.
  labelColor?: string;
};

export function Button({ label, variant = "primary", labelColor, disabled, ...rest }: ButtonProps) {
  const theme = useTheme();
  const isPrimary = variant === "primary";

  return (
    <Pressable
      {...rest}
      disabled={disabled}
      style={({ pressed }) => [
        styles.button,
        {
          backgroundColor: isPrimary ? theme.colors.chrome : theme.colors.surface,
          borderRadius: theme.radii.button,
          height: theme.spacing.buttonHeight,
          opacity: disabled ? 0.4 : 1,
          ...(isPrimary ? null : secondaryCard(theme.scheme === "light", theme.colors.cardEdge)),
          transform: [{ scale: pressed ? 0.97 : 1 }],
        },
      ]}
    >
      <Text
        variant="headline"
        tone={isPrimary ? "onChrome" : "ink"}
        style={labelColor ? { color: labelColor } : undefined}
      >
        {label}
      </Text>
    </Pressable>
  );
}

// Mirrors Card: hairline + soft shadow in light, hairline border only in dark.
function secondaryCard(isLight: boolean, borderColor: string) {
  return {
    borderWidth: StyleSheet.hairlineWidth,
    borderColor,
    ...(isLight ? { shadowColor: "#0E0E0C", shadowOpacity: 0.06, shadowRadius: 2, shadowOffset: { width: 0, height: 1 } } : null),
  };
}

const styles = StyleSheet.create({
  button: { alignItems: "center", justifyContent: "center", paddingHorizontal: 20 },
});
