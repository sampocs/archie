import { useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, ScrollView, View } from "react-native";

import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { Button } from "@/theme/components/Button";
import { GroupedList } from "@/ui/GroupedList";
import { haptic } from "@/ui/haptics";
import { useNow } from "@/ui/useNow";
import { TakeRow } from "@/takes/TakeRow";
import { filterTakes, TAKE_FILTER_LABELS, TAKE_FILTERS, takeFilterCounts, type TakeFilter } from "@/takes/takes";
import { useTakesData } from "@/takes/useTakesData";

const EMPTY_FILTER_LINES: Record<TakeFilter, string> = {
  all: "",
  opinion: "No opinions yet.",
  talking_point: "No talking points yet.",
};

/** Library's Takes mode: the owner's takes, most recently updated first, filtered by kind. */
export function TakesView() {
  const theme = useTheme();
  const router = useRouter();
  const takes = useTakesData();
  const now = useNow();
  const [filter, setFilter] = useState<TakeFilter>("all");

  if (takes.length === 0) {
    return (
      <View testID="takes-view" style={{ alignItems: "center", gap: theme.spacing.md, paddingVertical: theme.spacing.xl }}>
        <Text testID="takes-empty" tone="ink2">
          Things you think, in your own words
        </Text>
        <Button testID="takes-write" label="Write a take" variant="secondary" onPress={() => router.push("/take/edit")} />
      </View>
    );
  }

  const shown = filterTakes(takes, filter);

  return (
    <View testID="takes-view" style={{ gap: theme.spacing.lg }}>
      <FilterChips filter={filter} counts={takeFilterCounts(takes)} onChange={setFilter} />
      {shown.length === 0 ? (
        <Text testID="takes-filter-empty" tone="ink2">
          {EMPTY_FILTER_LINES[filter]}
        </Text>
      ) : (
        <GroupedList>
          {shown.map((take) => (
            <TakeRow key={take.id} take={take} now={now} />
          ))}
        </GroupedList>
      )}
    </View>
  );
}

function FilterChips(props: {
  filter: TakeFilter;
  counts: Record<TakeFilter, number>;
  onChange: (filter: TakeFilter) => void;
}) {
  const theme = useTheme();

  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: theme.spacing.sm }}>
      {TAKE_FILTERS.map((filter) => {
        const selected = filter === props.filter;
        const tone = selected ? "onChrome" : "ink2";
        return (
          <Pressable
            key={filter}
            testID={`takes-filter-${filter}`}
            onPress={() => {
              haptic("selection");
              props.onChange(filter);
            }}
            style={{
              flexDirection: "row",
              gap: theme.spacing.xs,
              paddingHorizontal: theme.spacing.md,
              paddingVertical: 7,
              borderRadius: 999,
              backgroundColor: selected ? theme.colors.chrome : theme.colors.surface,
            }}
          >
            <Text variant="secondary" tone={tone}>
              {TAKE_FILTER_LABELS[filter]}
            </Text>
            <Text testID={`takes-filter-count-${filter}`} variant="secondary" tone={tone} style={{ opacity: 0.55 }}>
              {props.counts[filter]}
            </Text>
          </Pressable>
        );
      })}
    </ScrollView>
  );
}
