import { AppRegistry } from "react-native";

import { ShareSheet } from "@/share/ShareSheet";

// expo-share-extension looks up the extension's root component by this exact name.
AppRegistry.registerComponent("shareExtension", () => ShareSheet);
