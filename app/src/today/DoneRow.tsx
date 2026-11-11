import { useEffect } from "react";
import { StyleSheet } from "react-native";
import Animated, { useAnimatedStyle, useReducedMotion, useSharedValue, withDelay, withSpring } from "react-native-reanimated";

import { Card } from "@/theme/components/Card";
import { Text } from "@/theme/components/Text";
import { fontFamily } from "@/theme/type";
import { useTheme } from "@/theme/useTheme";
import { haptic } from "@/ui/haptics";
import { Tappable } from "@/ui/Tappable";

// The row's check pops once the card above has mostly eased into the row.
const ROW_POP_DELAY_MS = 250;
const POP_SPRING = { damping: 9, stiffness: 220 };

type DoneRowProps = {
  title: string;
  detail?: string | null;
  // The right-hand link ("More ›"); tapping anywhere on the row does what it says.
  link?: string;
  onPress?: () => void;
  // Play the check's pop and a light haptic when the row appears; read once, when it mounts.
  celebrate: boolean;
  testID?: string;
};

/** A finished Today task in one line: a green check, the bold title · its detail, and an optional link. */
export function DoneRow({ title, detail, link, onPress, celebrate, testID }: DoneRowProps) {
  return (
    <Tappable
      testID={testID}
      accessibilityRole={onPress ? "button" : undefined}
      disabled={!onPress}
      onPress={() => {
        haptic("light");
        onPress?.();
      }}
    >
      <Card style={styles.row}>
        <PopCheck size={20} celebrate={celebrate} delayMs={ROW_POP_DELAY_MS} haptic="light" />
        <Text variant="secondary" numberOfLines={1} style={{ flex: 1 }}>
          <Text variant="secondary" style={{ fontFamily: fontFamily.semibold }}>
            {title}
          </Text>
          {detail ? ` · ${detail}` : null}
        </Text>
        {link ? (
          <Text variant="secondary" tone="ink2">
            {link}
          </Text>
        ) : null}
      </Card>
    </Tappable>
  );
}

type PopCheckProps = {
  size: number;
  celebrate: boolean;
  delayMs: number;
  haptic: "light" | "success";
  // Called as the pop lands (the day card's burst starts with it).
  onPop?: () => void;
};

/** The green ✓ disc; when celebrating it springs from nothing after `delayMs`, with a haptic (kept for Reduce Motion). */
export function PopCheck({ size, celebrate, delayMs, haptic: feedback, onPop }: PopCheckProps) {
  const theme = useTheme();
  const reduceMotion = useReducedMotion();
  const scale = useSharedValue(celebrate && !reduceMotion ? 0 : 1);
  const style = useAnimatedStyle(() => ({ transform: [{ scale: scale.value }] }));

  // Only the mount decides: a row that later stops being "fresh" keeps the pop it started.
  useEffect(() => {
    if (!celebrate) return;
    if (!reduceMotion) scale.value = withDelay(delayMs, withSpring(1, POP_SPRING));
    const timer = setTimeout(() => {
      haptic(feedback);
      onPop?.();
    }, delayMs);
    return () => clearTimeout(timer);
  }, []);

  return (
    <Animated.View
      style={[
        {
          width: size,
          height: size,
          borderRadius: size / 2,
          backgroundColor: theme.signals.gotIt,
          alignItems: "center",
          justifyContent: "center",
        },
        style,
      ]}
    >
      <Text style={{ color: "#FFFFFF", fontSize: size / 2, fontFamily: fontFamily.bold }}>✓</Text>
    </Animated.View>
  );
}

// Kept tighter than a card's padding so it reads as a line.
const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 10, paddingHorizontal: 13 },
});
