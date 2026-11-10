// Design tokens from docs/superpowers/specs/2026-10-29-ux-and-brand-design.md ("Color tokens").
// Graphite (chrome) is the UI; color appears only as a signal.

import type { DomainName } from "@/topics/domains";

export type ColorScheme = "light" | "dark";

export type ColorTokens = {
  bg: string;
  surface: string;
  ink: string;
  ink2: string;
  ink3: string;
  line: string;
  press: string;
  // A chat question's bubble: a step darker than `press`, so it stands off the page background.
  bubble: string;
  chrome: string;
  onChrome: string;
  unread: string;
  // Text on a domain-colored tile.
  onDomain: string;
};

export const colors: Record<ColorScheme, ColorTokens> = {
  light: {
    bg: "#F4F2EC",
    surface: "#FFFFFF",
    ink: "#0E0E0C",
    ink2: "#55534D",
    ink3: "#9A978F",
    line: "#E8E6DF",
    press: "#EFEDE6",
    bubble: "#E6E3DA",
    chrome: "#1C1B18",
    onChrome: "#FFFFFF",
    unread: "#3D7BF2",
    onDomain: "#FFFFFF",
  },
  dark: {
    bg: "#151412",
    surface: "#201F1C",
    ink: "#F1EFE9",
    ink2: "#B3AFA5",
    ink3: "#7E7A70",
    line: "#2D2B27",
    press: "#2A2824",
    bubble: "#2E2C28",
    chrome: "#F1EFE9",
    // Text on chrome flips in dark mode.
    onChrome: "#141311",
    unread: "#6EA1FF",
    onDomain: "#151412",
  },
};

export type Domain = DomainName;

export const domainColors: Record<ColorScheme, Record<Domain, string>> = {
  light: {
    Macro: "#3F7262",
    Finance: "#8A7533",
    Trading: "#4F6F8A",
    Crypto: "#A8613A",
    Startups: "#3D6690",
    AI: "#6A5A9C",
    Politics: "#8A4F4F",
    Geopolitics: "#5E6B3A",
    Sports: "#3A7A7A",
    Geography: "#7A6248",
    History: "#8E5468",
    "Software engineering": "#5A5F6E",
    Other: "#77736A",
  },
  dark: {
    Macro: "#79B39E",
    Finance: "#CDB46A",
    Trading: "#8FB0CC",
    Crypto: "#DC9867",
    Startups: "#7FA7D9",
    AI: "#A898DE",
    Politics: "#D58E8E",
    Geopolitics: "#A9B77A",
    Sports: "#7CC2C2",
    Geography: "#C7A783",
    History: "#C98BA0",
    "Software engineering": "#A3A8B8",
    Other: "#A9A59B",
  },
};

export type Signal = "gotIt" | "partly" | "missed" | "reviewCard" | "favorite";

export const signalColors: Record<ColorScheme, Record<Signal, string>> = {
  light: { gotIt: "#3F7262", partly: "#A97F22", missed: "#B04A3C", reviewCard: "#3F7262",
    // The favorites ★, and nothing else.
    favorite: "#B8892A",
  },
  dark: { gotIt: "#79B39E", partly: "#D6AC4E", missed: "#E3806F", reviewCard: "#2F5A4C",
    favorite: "#D9B45A",
  },
};

export const radii = {
  card: 18,
  reviewCard: 22,
  textBox: 22,
  button: 16,
  chip: 12,
  chipSmall: 8,
} as const;

export const spacing = {
  gutterCards: 16,
  gutterText: 22,
  section: 24,
  buttonHeight: 52,
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
} as const;

export type Theme = {
  scheme: ColorScheme;
  colors: ColorTokens;
  domains: Record<Domain, string>;
  signals: Record<Signal, string>;
  radii: typeof radii;
  spacing: typeof spacing;
};

export function buildTheme(scheme: ColorScheme): Theme {
  return {
    scheme,
    colors: colors[scheme],
    domains: domainColors[scheme],
    signals: signalColors[scheme],
    radii,
    spacing,
  };
}
