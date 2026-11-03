import { useColorScheme } from "react-native";

import { buildTheme, Theme } from "./tokens";

// Follows the system setting; unspecified falls back to light.
export function useTheme(): Theme {
  const scheme = useColorScheme();
  return buildTheme(scheme === "dark" ? "dark" : "light");
}
