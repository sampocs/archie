import { Text } from "@/theme/components/Text";
import { asDomain } from "@/topics/domains";

type KickerProps = { domain: string | null; suffix?: string; label?: string };

/** "MACRO · 2 h ago": the domain-colored line above a row's title. `label` replaces the domain name. */
export function Kicker({ domain, suffix, label }: KickerProps) {
  const name = label ?? asDomain(domain);
  return (
    <Text variant="kicker" domain={asDomain(domain)} numberOfLines={1}>
      {suffix ? `${name} · ${suffix}` : name}
    </Text>
  );
}
