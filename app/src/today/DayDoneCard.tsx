import { useEffect } from "react";
import { StyleSheet, View } from "react-native";
import Animated, {
  Easing,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withDelay,
  withSpring,
  withTiming,
  type SharedValue,
} from "react-native-reanimated";

import { Text } from "@/theme/components/Text";
import { fontFamily } from "@/theme/type";
import { useTheme } from "@/theme/useTheme";
import { haptic } from "@/ui/haptics";

import { PopCheck } from "./DoneRow";

// The approved mock's timings, from the moment the card replaces the done rows (which fade while it comes in).
const CARD_DELAY_MS = 350;
const CHECK_POP_MS = 700;
const BURST_MS = 700;
const FIRST_CHIP_MS = 900;
const CHIP_STEP_MS = 100;
const CHIP_FADE_MS = 300;
const CHECK_SIZE = 28;
// Where the burst's seven dots fly to, from the check's centre.
const BURST_OFFSETS = [
  [-34, -26],
  [30, -30],
  [40, 8],
  [-40, 12],
  [4, -42],
  [18, 34],
  [-16, 36],
] as const;
const BURST_DOT = 6;
// Over the surface: the green's tint (12%) fill and a 25% border, as hex alpha.
const TINT_ALPHA = "1F";
const BORDER_ALPHA = "40";

type DayDoneCardProps = {
  backTomorrow: string;
  chips: string[];
  // Spring in with the burst and the ticking chips; read once, when it mounts.
  celebrate: boolean;
};

/** "Today's done": every task finished today, what tomorrow holds, and a ticked chip per finished task. */
export function DayDoneCard({ backTomorrow, chips, celebrate }: DayDoneCardProps) {
  const theme = useTheme();
  const reduceMotion = useReducedMotion();
  const animate = celebrate && !reduceMotion;
  const appear = useSharedValue(animate ? 0 : 1);
  const burst = useSharedValue(0);
  const cardStyle = useAnimatedStyle(() => ({
    opacity: appear.value,
    transform: [{ scale: 0.92 + 0.08 * appear.value }],
  }));

  // The card springs in; each chip's haptic lands with its tick (Reduce Motion keeps the haptics, not the motion).
  useEffect(() => {
    if (!celebrate) return;
    if (!reduceMotion) appear.value = withDelay(CARD_DELAY_MS, withSpring(1, { damping: 12, stiffness: 160 }));
    const timers = chips.map((_, index) =>
      setTimeout(() => haptic("light"), FIRST_CHIP_MS + index * CHIP_STEP_MS),
    );
    return () => timers.forEach(clearTimeout);
  }, []);

  return (
    <Animated.View
      testID="today-done"
      style={[
        styles.card,
        {
          backgroundColor: theme.colors.surface,
          borderColor: `${theme.signals.gotIt}${BORDER_ALPHA}`,
          borderRadius: theme.radii.reviewCard,
          padding: theme.spacing.lg,
        },
        cardStyle,
      ]}
    >
      <View
        pointerEvents="none"
        style={[
          StyleSheet.absoluteFill,
          { backgroundColor: `${theme.signals.gotIt}${TINT_ALPHA}`, borderRadius: theme.radii.reviewCard },
        ]}
      />
      <View>
        {animate ? <Burst progress={burst} /> : null}
        <PopCheck
          size={CHECK_SIZE}
          celebrate={celebrate}
          delayMs={CHECK_POP_MS}
          haptic="success"
          onPop={() => {
            burst.value = withTiming(1, { duration: BURST_MS, easing: Easing.out(Easing.quad) });
          }}
        />
      </View>
      <Text variant="articleTitle">Today's done</Text>
      <Text testID="today-done-tomorrow" variant="secondary" tone="ink2">
        {backTomorrow}
      </Text>
      <View style={styles.chips}>
        {chips.map((chip, index) => (
          <Chip key={chip} label={chip} animate={animate} delayMs={FIRST_CHIP_MS + index * CHIP_STEP_MS} />
        ))}
      </View>
    </Animated.View>
  );
}

function Chip({ label, animate, delayMs }: { label: string; animate: boolean; delayMs: number }) {
  const theme = useTheme();
  const shown = useSharedValue(animate ? 0 : 1);
  const style = useAnimatedStyle(() => ({
    opacity: shown.value,
    transform: [{ translateY: 6 * (1 - shown.value) }],
  }));

  useEffect(() => {
    if (animate) shown.value = withDelay(delayMs, withTiming(1, { duration: CHIP_FADE_MS }));
  }, []);

  return (
    <Animated.View
      style={[styles.chip, { backgroundColor: theme.colors.surface, borderColor: theme.colors.line }, style]}
    >
      <Text variant="secondary" style={{ color: theme.signals.gotIt, fontFamily: fontFamily.bold }}>
        ✓
      </Text>
      <Text variant="secondary" tone="ink2">
        {label}
      </Text>
    </Animated.View>
  );
}

// Seven dots that fly out from the check's centre and fade as it pops.
function Burst({ progress }: { progress: SharedValue<number> }) {
  return (
    <View pointerEvents="none" style={[styles.burst, { left: CHECK_SIZE / 2, top: CHECK_SIZE / 2 }]}>
      {BURST_OFFSETS.map(([x, y], index) => (
        <BurstDot key={index} x={x} y={y} progress={progress} />
      ))}
    </View>
  );
}

function BurstDot({ x, y, progress }: { x: number; y: number; progress: SharedValue<number> }) {
  const theme = useTheme();
  const style = useAnimatedStyle(() => ({
    // Hidden until the pop starts it, then gone as it lands.
    opacity: progress.value > 0 ? 1 - progress.value : 0,
    transform: [
      { translateX: x * progress.value },
      { translateY: y * progress.value },
      { scale: 1 - 0.6 * progress.value },
    ],
  }));
  return <Animated.View style={[styles.dot, { backgroundColor: theme.signals.gotIt }, style]} />;
}

const styles = StyleSheet.create({
  // Not clipped, so the burst can fly past the card's edge.
  card: { borderWidth: StyleSheet.hairlineWidth, gap: 6, alignItems: "flex-start" },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 4 },
  chip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 5,
    borderRadius: 999,
    borderWidth: StyleSheet.hairlineWidth,
    paddingHorizontal: 9,
    paddingVertical: 4,
  },
  burst: { position: "absolute", width: 0, height: 0 },
  dot: {
    position: "absolute",
    width: BURST_DOT,
    height: BURST_DOT,
    borderRadius: BURST_DOT / 2,
    left: -BURST_DOT / 2,
    top: -BURST_DOT / 2,
  },
});
