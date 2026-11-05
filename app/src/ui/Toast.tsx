import { useEffect } from "react";
import { Pressable, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";

type ToastProps = { message: string; actionLabel: string; onAction: () => void; onHide: () => void };

const VISIBLE_MS = 4000;

/** A short confirmation pinned to the bottom with one action (e.g. Undo); it hides itself after a few seconds. */
export function Toast({ message, actionLabel, onAction, onHide }: ToastProps) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();

  useEffect(() => {
    const timer = setTimeout(onHide, VISIBLE_MS);
    return () => clearTimeout(timer);
  }, [onHide]);

  return (
    <View
      testID="toast"
      style={{
        position: "absolute",
        left: theme.spacing.gutterCards,
        right: theme.spacing.gutterCards,
        bottom: insets.bottom + theme.spacing.lg,
        flexDirection: "row",
        alignItems: "center",
        justifyContent: "space-between",
        backgroundColor: theme.colors.chrome,
        borderRadius: theme.radii.chip,
        paddingHorizontal: theme.spacing.lg,
        paddingVertical: theme.spacing.md,
      }}
    >
      <Text tone="onChrome">{message}</Text>
      <Pressable
        testID="toast-action"
        hitSlop={12}
        onPress={() => {
          onAction();
          onHide();
        }}
      >
        <Text variant="headline" tone="onChrome">
          {actionLabel}
        </Text>
      </Pressable>
    </View>
  );
}
