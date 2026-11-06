import { ReactNode, useContext } from "react";
import {
  KeyboardAvoidingView,
  NativeScrollEvent,
  NativeSyntheticEvent,
  Pressable,
  StyleSheet,
  View,
} from "react-native";
// Gesture handler's ScrollView lets a drag handle's pan (the queue) win over scrolling.
import { ScrollView } from "react-native-gesture-handler";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { TabBarInsetContext } from "../tabBarInset";
import { useTheme } from "../useTheme";
import { Text } from "./Text";

type ScreenProps = {
  title: string;
  children?: ReactNode;
  headerRight?: ReactNode;
  onBack?: () => void;
  // Pinned below the scrolling content, e.g. a long form's submit button.
  footer?: ReactNode;
  // Pinned between the header and the scrolling content, e.g. a reading-progress bar.
  subheader?: ReactNode;
  onScroll?: (event: NativeSyntheticEvent<NativeScrollEvent>) => void;
  // Presented as a modal sheet: the sheet already sits below the status bar, so no top safe-area inset.
  sheet?: boolean;
};

// Enough scroll events for a smooth progress bar without re-rendering on every frame.
const SCROLL_EVENT_THROTTLE_MS = 32;

export function Screen({ title, children, headerRight, onBack, footer, subheader, onScroll, sheet }: ScreenProps) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const tabBarInset = useContext(TabBarInsetContext);

  // A pinned footer rides above the keyboard; otherwise a typed-in field would hide the screen's submit button.
  // Only footer screens opt in: tab screens sit above the tab bar, which the keyboard's height already includes.
  return (
    <KeyboardAvoidingView
      behavior="padding"
      enabled={footer !== undefined}
      style={[styles.root, { backgroundColor: theme.colors.bg, paddingTop: sheet ? theme.spacing.md : insets.top }]}
    >
      <View style={[styles.header, { paddingHorizontal: theme.spacing.gutterText }]}>
        <View style={styles.titleGroup}>
          {onBack ? (
            <Pressable testID="screen-back" onPress={onBack} hitSlop={12}>
              <Text variant="largeTitle">‹</Text>
            </Pressable>
          ) : null}
          <Text variant="largeTitle">{title}</Text>
        </View>
        {headerRight}
      </View>
      {subheader}
      <ScrollView
        onScroll={onScroll}
        scrollEventThrottle={onScroll ? SCROLL_EVENT_THROTTLE_MS : undefined}
        contentContainerStyle={{
          padding: theme.spacing.gutterCards,
          paddingBottom: theme.spacing.gutterCards + tabBarInset,
          gap: theme.spacing.section,
        }}
        scrollIndicatorInsets={{ bottom: tabBarInset }}
        keyboardShouldPersistTaps="handled"
        // Scrolls a focused field (search, adding a topic) above the keyboard.
        automaticallyAdjustKeyboardInsets
      >
        {children}
      </ScrollView>
      {footer ? (
        <View
          style={{
            paddingHorizontal: theme.spacing.gutterCards,
            paddingTop: theme.spacing.md,
            paddingBottom: insets.bottom + theme.spacing.md,
            borderTopWidth: StyleSheet.hairlineWidth,
            borderTopColor: theme.colors.line,
          }}
        >
          {footer}
        </View>
      ) : null}
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  titleGroup: { flexDirection: "row", alignItems: "center", gap: 8, flexShrink: 1 },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingVertical: 12 },
});
