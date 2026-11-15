import { Ionicons } from "@expo/vector-icons";
import { randomUUID } from "expo-crypto";
import * as Network from "expo-network";
import { useRouter } from "expo-router";
import { useContext } from "react";
import { Keyboard, KeyboardAvoidingView, Pressable, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Composer } from "@/ask/Composer";
import { useAskAvailable } from "@/ask/useAskAvailable";
import { Screen } from "@/theme/components/Screen";
import { Text } from "@/theme/components/Text";
import { TabBarInsetContext } from "@/theme/tabBarInset";
import { useTheme } from "@/theme/useTheme";

const HISTORY_ICON_SIZE = 16;
const HISTORY_PILL_HEIGHT = 34;

/** The Ask tab only starts chats: History in the corner, then one big question box. */
export default function AskScreen() {
  const theme = useTheme();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const tabBarInset = useContext(TabBarInsetContext);
  const available = useAskAvailable();
  const network = Network.useNetworkState();
  const online = network.isConnected !== false && network.isInternetReachable !== false;

  if (available === false) {
    return (
      <Screen title="Ask">
        <Text testID="ask-unavailable" tone="ink2">
          Ask isn't available on this account
        </Text>
      </Screen>
    );
  }

  // The keyboard's height already includes the floating tab bar's, so the offset takes it back off: with the keyboard
  // up the box sits just above it, and with it down the page clears the tab bar.
  return (
    <KeyboardAvoidingView
      behavior="padding"
      keyboardVerticalOffset={-tabBarInset}
      style={{ flex: 1, backgroundColor: theme.colors.bg, paddingTop: insets.top }}
    >
      <Pressable
        accessible={false}
        onPress={Keyboard.dismiss}
        style={{ flex: 1, paddingHorizontal: theme.spacing.gutterText, paddingBottom: tabBarInset }}
      >
        <View style={{ flexDirection: "row", paddingVertical: 12 }}>
          <Pressable
            testID="ask-history"
            accessibilityRole="button"
            onPress={() => {
              Keyboard.dismiss();
              router.push("/ask/history");
            }}
            hitSlop={8}
            style={{
              flexDirection: "row",
              alignItems: "center",
              gap: theme.spacing.sm,
              height: HISTORY_PILL_HEIGHT,
              paddingHorizontal: theme.spacing.md,
              borderRadius: HISTORY_PILL_HEIGHT / 2,
              backgroundColor: theme.colors.press,
            }}
          >
            <Ionicons name="time-outline" size={HISTORY_ICON_SIZE} color={theme.colors.ink} />
            <Text variant="secondary">History</Text>
          </Pressable>
        </View>
        {/* Spacers above and below (1 : 2) hold the question about a third of the way down, and lift it with the keyboard. */}
        <View style={{ flex: 1 }} />
        <View style={{ gap: theme.spacing.lg }}>
          <Text variant="articleTitle">What do you want to understand?</Text>
          <Composer
            variant="hero"
            placeholder="Ask about anything"
            disabled={!online}
            disabledLabel="Ask needs a connection"
            onSend={(text, web) =>
              router.push({ pathname: "/ask/[id]", params: { id: randomUUID(), q: text, web: web ? "1" : "0" } })
            }
          />
        </View>
        <View style={{ flex: 2 }} />
      </Pressable>
    </KeyboardAvoidingView>
  );
}
