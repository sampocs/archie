import { Text } from "@/theme/components/Text";
import { asDomain } from "@/topics/domains";

type KickerProps = { domain: string | null; suffix?: string; label?: string; testID?: string };

/** "MACRO · 2 h ago": the domain-colored line above a row's title. `label` replaces the domain name. */
export function Kicker({ domain, suffix, label, testID }: KickerProps) {
  const name = label ?? asDomain(domain);
  return (
    <Text testID={testID} variant="kicker" domain={asDomain(domain)} numberOfLines={1}>
      {suffix ? `${name} · ${suffix}` : name}
    </Text>
  );
}
