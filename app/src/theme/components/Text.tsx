import { Text as NativeText, TextProps as NativeTextProps } from "react-native";

import { useAllowFontScaling } from "../fontScaling";
import { textStyles, TextVariant } from "../type";
import { Domain } from "../tokens";
import { useTheme } from "../useTheme";

type Tone = "ink" | "ink2" | "ink3" | "onChrome";

type TextProps = NativeTextProps & {
  variant?: TextVariant;
  tone?: Tone;
  // Kickers are colored text in the domain color.
  domain?: Domain;
};

export function Text({ variant = "body", tone = "ink", domain, style, ...rest }: TextProps) {
  const theme = useTheme();
  const color = domain ? theme.domains[domain] : theme.colors[tone];
  const allowFontScaling = useAllowFontScaling();

  return <NativeText allowFontScaling={allowFontScaling} {...rest} style={[textStyles[variant], { color }, style]} />;
}
