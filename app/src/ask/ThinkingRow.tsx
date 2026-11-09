import { type ReactNode, useEffect, useRef, useState } from "react";
import { AccessibilityInfo, Animated, Easing, View } from "react-native";

import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";

type ThinkingRowProps = { label: string; startedAt: number };

const DOT_SIZE = 5;
const DOT_COUNT = 3;
const BOB_MS = 1000;
// Each dot starts this much after the one before, so they bob in turn.
const DOT_STAGGER_MS = 150;
const SHIMMER_MS = 900;

// The colour Ask's activity is shown in: the brand's "AI" signal.
const AI_DOMAIN = "AI";

/**
 * Ask at work, from send until text streams: three typing dots bobbing in turn, the label shimmering ("Thinking",
 * "Drafting cards…") and the seconds since the question was sent. With Reduce Motion on, the dots and label hold still.
 */
export function ThinkingRow({ label, startedAt }: ThinkingRowProps) {
  const theme = useTheme();
  const reduceMotion = useReduceMotion();
  const seconds = useElapsedSeconds(startedAt);

  return (
    <View testID="chat-thinking" style={{ flexDirection: "row", alignItems: "center", gap: theme.spacing.sm }}>
      <View style={{ flexDirection: "row", gap: 3, paddingVertical: theme.spacing.xs }}>
        {Array.from({ length: DOT_COUNT }, (_, index) => (
          <Dot key={index} delay={index * DOT_STAGGER_MS} still={reduceMotion} color={theme.domains[AI_DOMAIN]} />
        ))}
      </View>
      <Shimmer still={reduceMotion}>
        <Text testID="chat-thinking-label" tone="ink2" variant="secondary">
          {label}
        </Text>
      </Shimmer>
      <Text testID="chat-thinking-seconds" variant="monoLabel" tone="ink3">
        {`${seconds}s`}
      </Text>
    </View>
  );
}

function Dot({ delay, still, color }: { delay: number; still: boolean; color: string }) {
  const progress = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    if (still) return;
    const step = (toValue: number) =>
      Animated.timing(progress, { toValue, duration: BOB_MS * 0.4, easing: Easing.inOut(Easing.ease), useNativeDriver: true });
    // Only the first bob waits for its turn; after that every dot keeps the same one-second beat.
    const bob = Animated.sequence([
      Animated.delay(delay),
      Animated.loop(Animated.sequence([step(1), step(0), Animated.delay(BOB_MS * 0.2)])),
    ]);
    bob.start();
    return () => bob.stop();
  }, [delay, still, progress]);

  const style = still
    ? { opacity: 0.6 }
    : {
        opacity: progress.interpolate({ inputRange: [0, 1], outputRange: [0.35, 1] }),
        transform: [{ translateY: progress.interpolate({ inputRange: [0, 1], outputRange: [0, -3] }) }],
      };
  return (
    <Animated.View
      style={[{ width: DOT_SIZE, height: DOT_SIZE, borderRadius: DOT_SIZE / 2, backgroundColor: color }, style]}
    />
  );
}

// React Native has no gradient-clipped text, so the shimmer is a slow brightness pulse over the label.
function Shimmer({ still, children }: { still: boolean; children: ReactNode }) {
  const opacity = useRef(new Animated.Value(1)).current;

  useEffect(() => {
    if (still) {
      opacity.setValue(1);
      return;
    }
    const pulse = Animated.loop(
      Animated.sequence([
        Animated.timing(opacity, { toValue: 0.45, duration: SHIMMER_MS, useNativeDriver: true }),
        Animated.timing(opacity, { toValue: 1, duration: SHIMMER_MS, useNativeDriver: true }),
      ]),
    );
    pulse.start();
    return () => pulse.stop();
  }, [still, opacity]);

  return <Animated.View style={{ opacity }}>{children}</Animated.View>;
}

function useReduceMotion(): boolean {
  const [reduce, setReduce] = useState(false);
  useEffect(() => {
    let live = true;
    void AccessibilityInfo.isReduceMotionEnabled().then((enabled) => {
      if (live) setReduce(enabled);
    });
    const subscription = AccessibilityInfo.addEventListener("reduceMotionChanged", setReduce);
    return () => {
      live = false;
      subscription.remove();
    };
  }, []);
  return reduce;
}

function useElapsedSeconds(startedAt: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  return Math.max(0, Math.floor((now - startedAt) / 1000));
}
