// Design tokens from docs/superpowers/specs/2026-10-29-ux-and-brand-design.md ("Color tokens").
// Graphite (chrome) is the UI; color appears only as a signal.

export type ColorScheme = "light" | "dark";

export type ColorTokens = {
  bg: string;
  surface: string;
  ink: string;
  ink2: string;
  ink3: string;
  line: string;
  press: string;
  chrome: string;
  onChrome: string;
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
    chrome: "#1C1B18",
    onChrome: "#FFFFFF",
  },
  dark: {
    bg: "#151412",
    surface: "#201F1C",
    ink: "#F1EFE9",
    ink2: "#B3AFA5",
    ink3: "#7E7A70",
    line: "#2D2B27",
    press: "#2A2824",
    chrome: "#F1EFE9",
    // Text on chrome flips in dark mode.
    onChrome: "#141311",
  },
};

export type Domain = "macro" | "ai" | "crypto" | "startups" | "finance" | "history";

export const domainColors: Record<ColorScheme, Record<Domain, string>> = {
  light: {
    macro: "#3F7262",
    ai: "#6A5A9C",
    crypto: "#A8613A",
    startups: "#3D6690",
    finance: "#8A7533",
    history: "#8E5468",
  },
  dark: {
    macro: "#79B39E",
    ai: "#A898DE",
    crypto: "#DC9867",
    startups: "#7FA7D9",
    finance: "#CDB46A",
    history: "#C98BA0",
  },
};

export type Signal = "gotIt" | "partly" | "missed" | "reviewCard";

export const signalColors: Record<ColorScheme, Record<Signal, string>> = {
  light: { gotIt: "#3F7262", partly: "#A97F22", missed: "#B04A3C", reviewCard: "#3F7262" },
  dark: { gotIt: "#79B39E", partly: "#D6AC4E", missed: "#E3806F", reviewCard: "#2F5A4C" },
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
