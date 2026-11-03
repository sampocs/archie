import { ReactNode } from "react";
import { ScrollView, StyleSheet, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useTheme } from "../useTheme";
import { Text } from "./Text";

type ScreenProps = {
  title: string;
  children?: ReactNode;
  headerRight?: ReactNode;
};

export function Screen({ title, children, headerRight }: ScreenProps) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();

  return (
    <View style={[styles.root, { backgroundColor: theme.colors.bg, paddingTop: insets.top }]}>
      <View style={[styles.header, { paddingHorizontal: theme.spacing.gutterText }]}>
        <Text variant="largeTitle">{title}</Text>
        {headerRight}
      </View>
      <ScrollView
        contentContainerStyle={{ padding: theme.spacing.gutterCards, gap: theme.spacing.section }}
        keyboardShouldPersistTaps="handled"
      >
        {children}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingVertical: 12 },
});
