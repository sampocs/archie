import { useTheme } from "@/theme/useTheme";
import { Text } from "@/theme/components/Text";
import { asDomain } from "@/topics/domains";

type KickerProps = { domain: string | null; suffix?: string; label?: string; starred?: boolean; testID?: string };

/** "MACRO · 2 h ago": the domain-colored line above a row's title. `label` replaces the domain name. */
export function Kicker({ domain, suffix, label, starred, testID }: KickerProps) {
  const theme = useTheme();
  const name = label ?? asDomain(domain);
  return (
    <Text testID={testID} variant="kicker" domain={asDomain(domain)} numberOfLines={1}>
      {suffix ? `${name} · ${suffix}` : name}
      {starred ? <Text style={{ color: theme.signals.favorite }}> ★</Text> : null}
    </Text>
  );
}
