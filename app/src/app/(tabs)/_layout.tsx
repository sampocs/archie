import { Ionicons } from "@expo/vector-icons";
import { BlurView } from "expo-blur";
import { Tabs } from "expo-router";
import { StyleSheet, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useSyncStatus } from "@/sync/useSync";
import { Text } from "@/theme/components/Text";

import { fontFamily } from "@/theme/type";
import { useTheme } from "@/theme/useTheme";

type IconName = React.ComponentProps<typeof Ionicons>["name"];

const TAB_BAR_HEIGHT = 49;
const ADD_BUTTON_SIZE = 46;

const TABS: { name: string; title: string; icon: IconName }[] = [
  { name: "today", title: "Today", icon: "sunny-outline" },
  { name: "library", title: "Library", icon: "library-outline" },
  { name: "add", title: "", icon: "add" },
  { name: "review", title: "Review", icon: "refresh-circle-outline" },
  { name: "ask", title: "Ask", icon: "chatbubble-outline" },
];

// Sits above the (absolutely positioned) tab bar while pushes are failing.
function SyncStatusLine() {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const { waiting, offline } = useSyncStatus();
  if (!offline || waiting === 0) return null;

  return (
    <View
      testID="sync-status"
      pointerEvents="none"
      style={{ position: "absolute", left: 0, right: 0, bottom: TAB_BAR_HEIGHT + insets.bottom, alignItems: "center" }}
    >
      <View style={{ backgroundColor: theme.colors.press, borderRadius: theme.radii.chip, paddingHorizontal: 12, paddingVertical: 6 }}>
        <Text variant="secondary" tone="ink2">
          Offline · {waiting} {waiting === 1 ? "change" : "changes"} waiting
        </Text>
      </View>
    </View>
  );
}

// The middle tab: a filled chrome circle (inverts in dark mode) with the + in the on-chrome color, no label.
function AddCircle() {
  const theme = useTheme();

  return (
    <View
      style={{
        width: ADD_BUTTON_SIZE,
        height: ADD_BUTTON_SIZE,
        borderRadius: ADD_BUTTON_SIZE / 2,
        backgroundColor: theme.colors.chrome,
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <Ionicons name="add" size={30} color={theme.colors.onChrome} />
    </View>
  );
}

export default function TabsLayout() {
  const theme = useTheme();

  return (
    <View style={{ flex: 1 }}>
      <Tabs
        screenOptions={{
          headerShown: false,
          // Graphite is the chrome: the active tab is chrome, never a brand color.
          tabBarActiveTintColor: theme.colors.chrome,
          tabBarInactiveTintColor: theme.colors.ink3,
          tabBarLabelStyle: { fontFamily: fontFamily.medium, fontSize: 10.5 },
          tabBarStyle: { position: "absolute", backgroundColor: "transparent", borderTopColor: theme.colors.line },
          tabBarBackground: () => (
            <BlurView
              tint={theme.scheme === "dark" ? "systemChromeMaterialDark" : "systemChromeMaterialLight"}
              intensity={80}
              style={StyleSheet.absoluteFill}
            />
          ),
        }}
      >
        {TABS.map((tab) => (
          <Tabs.Screen
            key={tab.name}
            name={tab.name}
            options={{
              title: tab.title,
              tabBarButtonTestID: `tab-${tab.name}`,
              ...(tab.name === "add"
                ? { tabBarLabel: () => null, tabBarIcon: () => <AddCircle />, tabBarAccessibilityLabel: "Add" }
                : { tabBarIcon: ({ color, size }) => <Ionicons name={tab.icon} size={size} color={color as string} /> }),
            }}
          />
        ))}
      </Tabs>
      <SyncStatusLine />
    </View>
  );
}
