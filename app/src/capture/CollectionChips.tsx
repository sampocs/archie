import { Pressable, View } from "react-native";

import type { SharedCollection } from "@/collections/sharedCollectionsFormat";
import { Text } from "@/theme/components/Text";
import { TextField } from "@/theme/components/TextField";
import { useTheme } from "@/theme/useTheme";

import type { CollectionPick } from "./types";

type CollectionChipsProps = {
  collections: SharedCollection[];
  pick: CollectionPick;
  onPick: (pick: CollectionPick) => void;
};

// Share extension only. It cannot present action sheets or alerts, so the dropdown becomes chips and a new
// collection's name is typed inline. Keep this file to theme components and react-native.
export function CollectionChips({ collections, pick, onPick }: CollectionChipsProps) {
  const theme = useTheme();

  return (
    <View style={{ gap: theme.spacing.md }}>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: theme.spacing.sm }}>
        {collections.map((collection) => (
          <Chip
            key={collection.id}
            testID={`share-collection-${collection.id}`}
            label={collection.name}
            selected={pick.kind === "existing" && pick.id === collection.id}
            onPress={() => onPick({ kind: "existing", id: collection.id })}
          />
        ))}
        <Chip
          testID="share-collection-new"
          label="＋ New collection…"
          outlined
          selected={pick.kind === "new"}
          onPress={() => onPick({ kind: "new", name: pick.kind === "new" ? pick.name : "" })}
        />
      </View>

      {pick.kind === "new" && (
        <TextField
          testID="share-collection-name"
          value={pick.name}
          onChangeText={(name) => onPick({ kind: "new", name })}
          placeholder="Collection name"
          maxLength={100}
          autoFocus
        />
      )}
    </View>
  );
}

type ChipProps = { testID: string; label: string; selected: boolean; outlined?: boolean; onPress: () => void };

function Chip({ testID, label, selected, outlined = false, onPress }: ChipProps) {
  const theme = useTheme();

  return (
    <Pressable
      testID={testID}
      onPress={onPress}
      style={{
        paddingHorizontal: theme.spacing.md,
        paddingVertical: theme.spacing.sm,
        borderRadius: 999,
        backgroundColor: selected ? theme.colors.chrome : theme.colors.press,
        borderWidth: outlined && !selected ? 1 : 0,
        borderColor: theme.colors.ink3,
      }}
    >
      <Text variant="secondary" tone={selected ? "onChrome" : "ink2"}>
        {label}
      </Text>
    </Pressable>
  );
}
