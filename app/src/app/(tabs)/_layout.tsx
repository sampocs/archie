import { Ionicons } from "@expo/vector-icons";
import { BlurView } from "expo-blur";
import { Tabs } from "expo-router";
import { Text as RNText, StyleSheet, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useSyncStatus } from "@/sync/useSync";
import { TabBarInsetContext } from "@/theme/tabBarInset";
import { Text } from "@/theme/components/Text";

import { fontFamily } from "@/theme/type";
import { useTheme } from "@/theme/useTheme";

type IconName = React.ComponentProps<typeof Ionicons>["name"];

const TAB_BAR_HEIGHT = 49;

// Today is home, so it sits first as iOS apps put home, with Review beside it; the app opens on it (see app/index.tsx).
// The selected tab shows the filled icon and a heavier label, as iOS does; sizes stay put so nothing shifts.
const TABS: { name: string; title: string; icon: IconName; selectedIcon: IconName }[] = [
  { name: "today", title: "Today", icon: "sunny-outline", selectedIcon: "sunny" },
  { name: "review", title: "Review", icon: "refresh-circle-outline", selectedIcon: "refresh-circle" },
  { name: "library", title: "Library", icon: "library-outline", selectedIcon: "library" },
  { name: "ask", title: "Ask", icon: "chatbubble-outline", selectedIcon: "chatbubble" },
  { name: "settings", title: "Settings", icon: "settings-outline", selectedIcon: "settings" },
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

export default function TabsLayout() {
  const theme = useTheme();
  const insets = useSafeAreaInsets();

  return (
    <TabBarInsetContext.Provider value={TAB_BAR_HEIGHT + insets.bottom}>
      <View style={{ flex: 1 }}>
        <Tabs
          screenOptions={{
            headerShown: false,
            // Graphite is the chrome: the active tab is chrome, never a brand color.
            tabBarActiveTintColor: theme.colors.chrome,
            tabBarInactiveTintColor: theme.colors.ink3,
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
                tabBarIcon: ({ focused, color, size }) => (
                  <Ionicons name={focused ? tab.selectedIcon : tab.icon} size={size} color={color as string} />
                ),
                // Same box as the default label (one line, centred); only the weight changes when selected.
                tabBarLabel: ({ focused, color, children }) => (
                  <RNText
                    numberOfLines={1}
                    style={[
                      styles.tabLabel,
                      { color, fontFamily: focused ? fontFamily.semibold : fontFamily.medium },
                    ]}
                  >
                    {children}
                  </RNText>
                ),
              }}
            />
          ))}
        </Tabs>
        <SyncStatusLine />
      </View>
    </TabBarInsetContext.Provider>
  );
}

const styles = StyleSheet.create({
  tabLabel: { fontSize: 10.5, textAlign: "center", backgroundColor: "transparent" },
});
