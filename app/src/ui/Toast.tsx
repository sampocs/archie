import { useEffect } from "react";
import { Pressable, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";

// Without an action (e.g. a failure notice) it is just the message.
type ToastProps = { message: string; actionLabel?: string; onAction?: () => void; onHide: () => void };

const VISIBLE_MS = 4000;

/** A short message pinned to the bottom, with at most one action (e.g. Undo); it hides itself after a few seconds. */
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
      <Text tone="onChrome" style={{ flexShrink: 1 }}>
        {message}
      </Text>
      {actionLabel && onAction ? (
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
      ) : null}
    </View>
  );
}
