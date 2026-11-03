import {
  Geist_400Regular,
  Geist_500Medium,
  Geist_600SemiBold,
  Geist_700Bold,
} from "@expo-google-fonts/geist";
import { GeistMono_500Medium } from "@expo-google-fonts/geist-mono";
import { TextStyle } from "react-native";

// Passed to expo-font's useFonts in the root layout.
export const fontAssets = {
  Geist_400Regular,
  Geist_500Medium,
  Geist_600SemiBold,
  Geist_700Bold,
  GeistMono_500Medium,
};

export const fontFamily = {
  regular: "Geist_400Regular",
  medium: "Geist_500Medium",
  semibold: "Geist_600SemiBold",
  bold: "Geist_700Bold",
  mono: "GeistMono_500Medium",
} as const;

export type TextVariant =
  | "largeTitle"
  | "articleTitle"
  | "reviewQuestion"
  | "reviewQuestionCompact"
  | "headline"
  | "readingBody"
  | "body"
  | "secondary"
  | "kicker"
  | "monoLabel";

// Tracking in the spec is in em; React Native wants px, so letterSpacing = em * size.
// Geist ships static weights (no 650), so the 650 review question uses SemiBold (600).
export const textStyles: Record<TextVariant, TextStyle> = {
  largeTitle: { fontFamily: fontFamily.bold, fontSize: 32, letterSpacing: -0.04 * 32 },
  articleTitle: { fontFamily: fontFamily.bold, fontSize: 28, letterSpacing: -0.04 * 28 },
  reviewQuestion: { fontFamily: fontFamily.semibold, fontSize: 27 },
  reviewQuestionCompact: { fontFamily: fontFamily.semibold, fontSize: 21 },
  headline: { fontFamily: fontFamily.semibold, fontSize: 16, letterSpacing: -0.018 * 16 },
  readingBody: { fontFamily: fontFamily.regular, fontSize: 16, lineHeight: 16 * 1.62 },
  body: { fontFamily: fontFamily.regular, fontSize: 15 },
  secondary: { fontFamily: fontFamily.regular, fontSize: 13.5 },
  kicker: {
    fontFamily: fontFamily.semibold,
    fontSize: 10.5,
    letterSpacing: 0.06 * 10.5,
    textTransform: "uppercase",
  },
  monoLabel: { fontFamily: fontFamily.mono, fontSize: 11, textTransform: "uppercase" },
};
