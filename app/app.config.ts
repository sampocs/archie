import type { ExpoConfig } from "expo/config";

const config: ExpoConfig = {
  name: "Archie",
  slug: "archie",
  scheme: "archie",
  version: "1.0.0",
  orientation: "portrait",
  icon: "./assets/images/icon.png",
  userInterfaceStyle: "automatic",
  ios: {
    bundleIdentifier: "com.sampocs.archie",
    usesAppleSignIn: true,
    supportsTablet: false,
    // Same Apple team the share-extension spike was signed with.
    appleTeamId: "3W3H65F89G",
  },
  plugins: [
    "expo-router",
    "expo-sqlite",
    "expo-secure-store",
    "expo-apple-authentication",
    "expo-font",
    [
      "expo-splash-screen",
      { image: "./assets/images/splash-icon.png", resizeMode: "contain", backgroundColor: "#F4F2EC" },
    ],
  ],
  experiments: { typedRoutes: true },
};

export default config;
