import { ReactNode, useEffect, useMemo } from "react";
import { KeyboardAvoidingView, Modal, Pressable, View } from "react-native";
import { GestureDetector, GestureHandlerRootView, usePanGesture } from "react-native-gesture-handler";
import Animated, { useAnimatedStyle, useSharedValue, withSpring, withTiming } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { scheduleOnRN } from "react-native-worklets";

import { useTheme } from "@/theme/useTheme";

// A drag down the grabber past this distance, or a flick faster than this, closes the sheet; anything less springs back.
const CLOSE_DISTANCE = 90;
const CLOSE_VELOCITY = 800;
const CLOSE_SLIDE_MS = 180;

type BottomSheetProps = {
  visible: boolean;
  onClose: () => void;
  onDismiss?: () => void;
  children: ReactNode;
  testID?: string;
};

/**
 * A modal sheet that slides up over a dimmed backdrop. Tapping the backdrop closes it, and so does dragging the grabber
 * strip at the top down. Only that strip drags, so a sheet's own scrolling content keeps scrolling.
 */
export function BottomSheet({ visible, onClose, onDismiss, children, testID }: BottomSheetProps) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const offsetY = useSharedValue(0);

  // Each opening starts from rest, not from wherever the last drag-to-close left it.
  useEffect(() => {
    if (visible) offsetY.value = 0;
  }, [visible, offsetY]);

  const panConfig = useMemo(
    () => ({
      activeOffsetY: [-6, 6] as [number, number],
      onUpdate: (event: { translationY: number }) => {
        "worklet";
        offsetY.value = Math.max(0, event.translationY);
      },
      onDeactivate: (event: { translationY: number; velocityY: number }) => {
        "worklet";
        if (event.translationY > CLOSE_DISTANCE || event.velocityY > CLOSE_VELOCITY) {
          offsetY.value = withTiming(offsetY.value + 600, { duration: CLOSE_SLIDE_MS });
          scheduleOnRN(onClose);
          return;
        }
        offsetY.value = withSpring(0, { duration: 250 });
      },
    }),
    [offsetY, onClose],
  );
  const pan = usePanGesture(panConfig);
  const sheetStyle = useAnimatedStyle(() => ({ transform: [{ translateY: offsetY.value }] }));

  return (
    <Modal transparent visible={visible} animationType="slide" onRequestClose={onClose} onDismiss={onDismiss}>
      {/* A Modal is its own native root, so gestures inside it need their own handler root. */}
      <GestureHandlerRootView style={{ flex: 1 }}>
        {/* Sheets with a text field (add or rename a topic, a note) must sit above the keyboard, not under it. */}
        <KeyboardAvoidingView behavior="padding" style={{ flex: 1, justifyContent: "flex-end" }}>
          <Pressable
            testID={testID ? `${testID}-backdrop` : undefined}
            onPress={onClose}
            style={{ position: "absolute", top: 0, bottom: 0, left: 0, right: 0, backgroundColor: "rgba(0,0,0,0.6)" }}
          />
          <Animated.View
            testID={testID}
            style={[
              {
                backgroundColor: theme.colors.surface,
                borderTopLeftRadius: theme.radii.card,
                borderTopRightRadius: theme.radii.card,
                paddingHorizontal: theme.spacing.gutterCards,
                paddingBottom: insets.bottom + theme.spacing.lg,
                gap: theme.spacing.md,
              },
              sheetStyle,
            ]}
          >
            <GestureDetector gesture={pan}>
              {/* The whole top strip is the grabber's touch target, not just the 5pt bar. */}
              <View
                testID={testID ? `${testID}-grabber` : undefined}
                style={{ paddingTop: theme.spacing.md, paddingBottom: theme.spacing.xs, marginHorizontal: -theme.spacing.gutterCards }}
              >
                <View
                  style={{ alignSelf: "center", width: 36, height: 5, borderRadius: 3, backgroundColor: theme.colors.line }}
                />
              </View>
            </GestureDetector>
            {children}
          </Animated.View>
        </KeyboardAvoidingView>
      </GestureHandlerRootView>
    </Modal>
  );
}
