import { desc, isNull } from "drizzle-orm";
import { useLiveQuery } from "drizzle-orm/expo-sqlite";
import { useState } from "react";
import { Pressable, View } from "react-native";

import { db } from "@/db/client";
import * as schema from "@/db/schema";
import { Card } from "@/theme/components/Card";
import { Screen } from "@/theme/components/Screen";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";

type SourceRow = typeof schema.sources.$inferSelect;

export default function LibraryScreen() {
  const { data: sources } = useLiveQuery(
    db.select().from(schema.sources).where(isNull(schema.sources.deletedAt)).orderBy(desc(schema.sources.createdAt)),
  );

  return (
    <Screen title="Library">
      {sources.length === 0 ? (
        <Text tone="ink2">Nothing here yet. Paste a link in ＋.</Text>
      ) : (
        sources.map((source) => <SourceItem key={source.id} source={source} />)
      )}
    </Screen>
  );
}

function SourceItem({ source }: { source: SourceRow }) {
  const theme = useTheme();
  const [expanded, setExpanded] = useState(false);

  return (
    <Card testID={`source-${source.id}`} style={{ gap: theme.spacing.sm }}>
      <Text variant="headline" tone={source.title ? "ink" : "ink3"} numberOfLines={2}>
        {source.title ?? source.url}
      </Text>
      <View style={{ flexDirection: "row", alignItems: "center", gap: theme.spacing.sm }}>
        <View
          style={{
            backgroundColor: theme.colors.press,
            borderRadius: theme.radii.chipSmall,
            paddingHorizontal: theme.spacing.sm,
            paddingVertical: theme.spacing.xs,
          }}
        >
          <Text variant="monoLabel" tone="ink2">
            {source.state}
          </Text>
        </View>
        <Text variant="secondary" tone="ink3">
          {source.kind}
        </Text>
        {source.syncError ? (
          <Pressable testID={`source-error-${source.id}`} onPress={() => setExpanded((open) => !open)} hitSlop={8}>
            <Text variant="secondary" style={{ color: theme.signals.missed }}>
              ⚠ Not synced
            </Text>
          </Pressable>
        ) : null}
      </View>
      {source.syncError && expanded ? (
        <Text variant="secondary" tone="ink2">
          {source.syncError}
        </Text>
      ) : null}
    </Card>
  );
}
