import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { Pressable, View } from "react-native";

import { DomainsView } from "@/library/DomainsView";
import { LibraryList } from "@/library/LibraryList";
import { isLibraryFilter, type LibraryFilter } from "@/library/sections";
import { useLibraryData } from "@/library/useLibraryData";
import { Screen } from "@/theme/components/Screen";
import { Text } from "@/theme/components/Text";
import { TextField } from "@/theme/components/TextField";
import { useTheme } from "@/theme/useTheme";
import { haptic } from "@/ui/haptics";

const HEADER_ADD_SIZE = 36;

type Mode = "list" | "domains";

const MODES: { mode: Mode; label: string }[] = [
  { mode: "list", label: "List" },
  { mode: "domains", label: "Domains" },
];

export default function LibraryScreen() {
  const theme = useTheme();
  const router = useRouter();
  const data = useLibraryData();
  const params = useLocalSearchParams<{ filter?: string; at?: string }>();
  const [mode, setMode] = useState<Mode>("list");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<LibraryFilter>(isLibraryFilter(params.filter) ? params.filter : "all");

  // Today links here with a filter (and a fresh `at`, so the same link works twice) while the tab may be mounted.
  useEffect(() => {
    if (!isLibraryFilter(params.filter)) return;
    setMode("list");
    setFilter(params.filter);
    setQuery("");
  }, [params.filter, params.at]);

  const showList = mode === "list" || query.trim() !== "";

  return (
    <Screen
      title="Library"
      headerRight={
        // Adding starts here now that the ＋ tab is gone: the same filled chrome circle, opening the add sheet.
        <Pressable
          testID="library-add"
          accessibilityLabel="Add"
          onPress={() => {
            haptic("light");
            router.push("/add");
          }}
          hitSlop={8}
          style={{
            width: HEADER_ADD_SIZE,
            height: HEADER_ADD_SIZE,
            borderRadius: HEADER_ADD_SIZE / 2,
            backgroundColor: theme.colors.chrome,
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <Ionicons name="add" size={24} color={theme.colors.onChrome} />
        </Pressable>
      }
    >
      <View style={{ flexDirection: "row", backgroundColor: theme.colors.press, borderRadius: theme.radii.chip, padding: 3 }}>
        {MODES.map((option) => (
          <Pressable
            key={option.mode}
            testID={`library-mode-${option.mode}`}
            onPress={() => {
              haptic("selection");
              setMode(option.mode);
            }}
            style={{
              flex: 1,
              alignItems: "center",
              paddingVertical: theme.spacing.sm,
              borderRadius: theme.radii.chip - 3,
              backgroundColor: mode === option.mode ? theme.colors.surface : "transparent",
            }}
          >
            <Text variant="secondary" tone={mode === option.mode ? "ink" : "ink2"}>
              {option.label}
            </Text>
          </Pressable>
        ))}
      </View>
      <TextField testID="library-search" placeholder="Search your library" value={query} onChangeText={setQuery} />
      {showList ? <LibraryList data={data} query={query} filter={filter} onFilterChange={setFilter} /> : <DomainsView data={data} />}
    </Screen>
  );
}
