import { createContext, useContext } from "react";

// In the share extension, text in a custom font that is allowed to scale measures zero high and
// draws nothing (expo-share-extension's README notes the same), so the share sheet turns scaling off.
export const FontScalingContext = createContext(true);

export function useAllowFontScaling(): boolean {
  return useContext(FontScalingContext);
}
