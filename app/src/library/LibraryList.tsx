import { useState } from "react";
import { Pressable, View } from "react-native";

import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { ProcessingLine } from "@/ui/ProcessingLine";
import { SourceRow } from "@/ui/SourceRow";
import { StatusTagView } from "@/ui/StatusTagView";

import type { LibraryData, LibrarySource } from "./join";
import { statusTag } from "./visibility";

type LibraryListProps = { data: LibraryData; query: string; initialFilter?: string };

/** Minimal list: every source newest first. Filters, queue, swipe and search arrive in a later task. */
export function LibraryList({ data, query }: LibraryListProps) {
  const needle = query.trim().toLowerCase();
  const sources = needle
    ? data.sources.filter((source) => (source.title ?? source.url).toLowerCase().includes(needle))
    : data.sources;

  if (sources.length === 0) return <Text tone="ink2">Nothing here yet. Paste a link in ＋.</Text>;

  return (
    <View>
      {sources.map((source) => (
        <LibraryItem key={source.id} source={source} />
      ))}
    </View>
  );
}

function LibraryItem({ source }: { source: LibrarySource }) {
  const theme = useTheme();
  const [expanded, setExpanded] = useState(false);

  return (
    <View testID={`source-${source.id}`}>
      <SourceRow
        source={source}
        testID={`source-row-${source.id}`}
        end={
          <View style={{ alignItems: "flex-end", gap: theme.spacing.xs }}>
            <StatusTagView tag={statusTag(source)} />
            {source.syncError ? (
              <Pressable testID={`source-error-${source.id}`} onPress={() => setExpanded((open) => !open)} hitSlop={8}>
                <Text variant="secondary" style={{ color: theme.signals.missed }}>
                  ⚠ Not synced
                </Text>
              </Pressable>
            ) : null}
          </View>
        }
      />
      {source.kind === "newsletter" ? (
        <Text testID={`source-sender-${source.id}`} variant="secondary" tone="ink3" numberOfLines={1}>
          {source.sender ?? "Newsletter"}
        </Text>
      ) : null}
      {source.syncError && expanded ? (
        <Text variant="secondary" tone="ink2">
          {source.syncError}
        </Text>
      ) : null}
      <ProcessingLine source={source} />
    </View>
  );
}
