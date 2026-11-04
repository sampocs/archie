import { View } from "react-native";

import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { DOMAINS } from "@/topics/domains";
import { slugify } from "@/topics/topicName";
import { GroupedList } from "@/ui/GroupedList";

import type { LibraryData } from "./join";

type DomainsViewProps = { data: LibraryData };

/** Minimal Domains view: one row per domain that has items, with a count. Topic navigation arrives later. */
export function DomainsView({ data }: DomainsViewProps) {
  const theme = useTheme();
  const rows = DOMAINS.map((domain) => ({
    domain,
    count: data.sources.filter((source) => source.domain === domain).length,
  })).filter((row) => row.count > 0);

  if (rows.length === 0) return <Text tone="ink2">No domains yet.</Text>;

  return (
    <GroupedList title="Domains">
      {rows.map((row) => (
        <View
          key={row.domain}
          testID={`domain-${slugify(row.domain)}`}
          style={{ flexDirection: "row", justifyContent: "space-between", paddingVertical: theme.spacing.md }}
        >
          <Text variant="headline" domain={row.domain}>
            {row.domain}
          </Text>
          <Text tone="ink3">{row.count}</Text>
        </View>
      ))}
    </GroupedList>
  );
}
