import { StyleSheet, View, ViewProps } from "react-native";

import { useTheme } from "../useTheme";

// Light: hairline + 2px soft shadow. Dark: no shadow, faint hairline border.
export function Card({ style, ...rest }: ViewProps) {
  const theme = useTheme();
  const isLight = theme.scheme === "light";

  return (
    <View
      {...rest}
      style={[
        styles.card,
        {
          backgroundColor: theme.colors.surface,
          borderColor: theme.colors.line,
          borderRadius: theme.radii.card,
          padding: theme.spacing.lg,
        },
        isLight && styles.shadow,
        style,
      ]}
    />
  );
}

const styles = StyleSheet.create({
  card: { borderWidth: StyleSheet.hairlineWidth },
  shadow: {
    shadowColor: "#0E0E0C",
    shadowOpacity: 0.06,
    shadowRadius: 2,
    shadowOffset: { width: 0, height: 1 },
  },
});
