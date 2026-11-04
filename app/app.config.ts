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
    // Before expo-share-extension on purpose: mods run last-listed first, and this one patches its target.
    "./plugins/withSharedKeychain.js",
    "./plugins/withShareSheetFrame.js",
    [
      "expo-share-extension",
      {
        activationRules: [{ type: "url" }, { type: "text" }],
        preprocessingFile: "./preprocessing.js",
        // The theme's light `bg` (#F4F2EC) as RGBA.
        backgroundColor: { red: 244, green: 242, blue: 236, alpha: 1 },
      },
    ],
  ],
  extra: { apiUrl: process.env.EXPO_PUBLIC_API_URL },
  experiments: { typedRoutes: true },
};

export default config;
