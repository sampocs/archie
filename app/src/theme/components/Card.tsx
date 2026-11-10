import { StyleSheet, View, ViewProps } from "react-native";

import { useTheme } from "../useTheme";

// Light: hairline + 2px soft shadow. Dark: no shadow; a 1pt `cardEdge` border carries the edge instead.
export function Card({ style, ...rest }: ViewProps) {
  const theme = useTheme();
  const isLight = theme.scheme === "light";

  return (
    <View
      {...rest}
      style={[
        {
          backgroundColor: theme.colors.surface,
          borderColor: theme.colors.cardEdge,
          borderWidth: isLight ? StyleSheet.hairlineWidth : 1,
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
  shadow: {
    shadowColor: "#0E0E0C",
    shadowOpacity: 0.06,
    shadowRadius: 2,
    shadowOffset: { width: 0, height: 1 },
  },
});
