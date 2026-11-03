import { Ionicons } from "@expo/vector-icons";
import { BlurView } from "expo-blur";
import { Tabs } from "expo-router";
import { StyleSheet } from "react-native";

import { fontFamily } from "@/theme/type";
import { useTheme } from "@/theme/useTheme";

type IconName = React.ComponentProps<typeof Ionicons>["name"];

const TABS: { name: string; title: string; icon: IconName }[] = [
  { name: "today", title: "Today", icon: "sunny-outline" },
  { name: "library", title: "Library", icon: "library-outline" },
  { name: "add", title: "＋", icon: "add-circle-outline" },
  { name: "review", title: "Review", icon: "refresh-circle-outline" },
  { name: "ask", title: "Ask", icon: "chatbubble-outline" },
];

export default function TabsLayout() {
  const theme = useTheme();

  return (
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
            tabBarIcon: ({ color, size }) => <Ionicons name={tab.icon} size={size} color={color as string} />,
          }}
        />
      ))}
    </Tabs>
  );
}
