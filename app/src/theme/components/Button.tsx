import { Pressable, PressableProps, StyleSheet } from "react-native";

import { useTheme } from "../useTheme";
import { Text } from "./Text";

type ButtonProps = Omit<PressableProps, "children" | "style"> & {
  label: string;
  // Primary is chrome (graphite); secondary is the quiet press-colored chip.
  variant?: "primary" | "secondary";
};

export function Button({ label, variant = "primary", disabled, ...rest }: ButtonProps) {
  const theme = useTheme();
  const isPrimary = variant === "primary";

  return (
    <Pressable
      {...rest}
      disabled={disabled}
      style={({ pressed }) => [
        styles.button,
        {
          backgroundColor: isPrimary ? theme.colors.chrome : theme.colors.press,
          borderRadius: theme.radii.button,
          height: theme.spacing.buttonHeight,
          opacity: disabled ? 0.4 : 1,
          transform: [{ scale: pressed ? 0.97 : 1 }],
        },
      ]}
    >
      <Text variant="headline" tone={isPrimary ? "onChrome" : "ink"}>
        {label}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  button: { alignItems: "center", justifyContent: "center", paddingHorizontal: 20 },
});
