import { ReactNode, useContext } from "react";
import {
  Keyboard,
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
  // A compact nav bar instead of the large title: "‹ backLabel" on the left, the title on one ellipsized line.
  nav?: { title: string; backLabel: string };
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

export function Screen({
  title,
  children,
  headerRight,
  onBack,
  nav,
  footer,
  subheader,
  onScroll,
  sheet,
}: ScreenProps) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const tabBarInset = useContext(TabBarInsetContext);
  // A page sheet has no tab bar, but its last control must still clear the home indicator.
  const bottomInset = sheet ? insets.bottom : tabBarInset;
  // A footer on a tab screen (Ask's composer) sits above the floating tab bar; with the keyboard up, the offset takes
  // the bar's height back off so the footer rides the keyboard as closely as anywhere else.
  const footerInset = Math.max(bottomInset, insets.bottom);

  // A pinned footer rides above the keyboard; otherwise a typed-in field would hide the screen's submit button.
  // The KAV is enabled only for footer screens; for a footer on a tab screen, keyboardVerticalOffset removes the tab
  // bar's height, which the keyboard's height already includes.
  return (
    <KeyboardAvoidingView
      behavior="padding"
      enabled={footer !== undefined}
      keyboardVerticalOffset={insets.bottom - footerInset}
      style={[styles.root, { backgroundColor: theme.colors.bg, paddingTop: sheet ? theme.spacing.md : insets.top }]}
    >
      {nav ? (
        <View style={[styles.header, { paddingHorizontal: theme.spacing.gutterText, gap: theme.spacing.md }]}>
          <Pressable testID="screen-back" onPress={onBack} hitSlop={12} style={styles.navSide}>
            <Text tone="ink2">‹ {nav.backLabel}</Text>
          </Pressable>
          <Text testID="screen-nav-title" variant="headline" numberOfLines={1} style={styles.navTitle}>
            {nav.title}
          </Text>
          <View style={[styles.navSide, styles.navRight]}>{headerRight}</View>
        </View>
      ) : (
        // Tapping the title area puts the keyboard away (e.g. after typing in Library search); buttons in it still win.
        <Pressable
          accessible={false}
          onPress={Keyboard.dismiss}
          style={[styles.header, { paddingHorizontal: theme.spacing.gutterText }]}
        >
          <View style={styles.titleGroup}>
            {onBack ? (
              <Pressable testID="screen-back" onPress={onBack} hitSlop={12}>
                <Text variant="largeTitle">‹</Text>
              </Pressable>
            ) : null}
            <Text variant="largeTitle">{title}</Text>
          </View>
          {headerRight}
        </Pressable>
      )}
      {subheader}
      <ScrollView
        onScroll={onScroll}
        scrollEventThrottle={onScroll ? SCROLL_EVENT_THROTTLE_MS : undefined}
        contentContainerStyle={{
          padding: theme.spacing.gutterCards,
          // A footer already clears the tab bar, so the content only needs a small gap above it.
          paddingBottom: theme.spacing.gutterCards + (footer ? theme.spacing.md : bottomInset),
          gap: theme.spacing.section,
        }}
        scrollIndicatorInsets={{ bottom: bottomInset }}
        keyboardShouldPersistTaps="handled"
        // Dragging the page puts the keyboard away, so controls under it (like the take editor's switch) are reachable.
        keyboardDismissMode="on-drag"
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
            paddingBottom: footerInset + theme.spacing.md,
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
  // Equal sides keep the nav title centred; the title shrinks and ellipsizes between them.
  navSide: { flexBasis: 64, flexGrow: 0, flexShrink: 0 },
  navRight: { alignItems: "flex-end" },
  navTitle: { flex: 1, textAlign: "center" },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingVertical: 12 },
});
