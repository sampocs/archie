import { useLocalSearchParams } from "expo-router";
import { useState } from "react";
import { Pressable, View } from "react-native";

import { DomainsView } from "@/library/DomainsView";
import { LibraryList } from "@/library/LibraryList";
import { useLibraryData } from "@/library/useLibraryData";
import { Screen } from "@/theme/components/Screen";
import { Text } from "@/theme/components/Text";
import { TextField } from "@/theme/components/TextField";
import { useTheme } from "@/theme/useTheme";
import { haptic } from "@/ui/haptics";

type Mode = "list" | "domains";

const MODES: { mode: Mode; label: string }[] = [
  { mode: "list", label: "List" },
  { mode: "domains", label: "Domains" },
];

export default function LibraryScreen() {
  const theme = useTheme();
  const data = useLibraryData();
  const { filter } = useLocalSearchParams<{ filter?: string }>();
  const [mode, setMode] = useState<Mode>("list");
  const [query, setQuery] = useState("");

  const showList = mode === "list" || query.trim() !== "";

  return (
    <Screen title="Library">
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
      {showList ? <LibraryList data={data} query={query} initialFilter={filter} /> : <DomainsView data={data} />}
    </Screen>
  );
}
