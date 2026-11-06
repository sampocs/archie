import { Alert } from "react-native";

/** Asks for a collection name with the system prompt; a blank answer does nothing. */
export function promptCollectionName(input: {
  title: string;
  submitLabel: string;
  initialName?: string;
  onSubmit: (name: string) => void;
}): void {
  Alert.prompt(
    input.title,
    undefined,
    [
      { text: "Cancel", style: "cancel" },
      {
        text: input.submitLabel,
        onPress: (value?: string) => {
          const name = value?.trim();
          if (name) input.onSubmit(name);
        },
      },
    ],
    "plain-text",
    input.initialName ?? "",
  );
}

/** Deleting a collection removes every post in it, so it asks first. */
export function confirmDeleteCollection(input: { name: string; count: number; onConfirm: () => void }): void {
  const message =
    input.count === 0 ? undefined : `Its ${input.count} saved ${input.count === 1 ? "post goes" : "posts go"} with it.`;
  Alert.alert(`Delete “${input.name}”?`, message, [
    { text: "Cancel", style: "cancel" },
    { text: "Delete", style: "destructive", onPress: input.onConfirm },
  ]);
}

/** Edit a post's note; saving a blank note clears it. */
export function promptNote(input: { initialNote: string; onSubmit: (note: string) => void }): void {
  Alert.prompt(
    "Note",
    undefined,
    [
      { text: "Cancel", style: "cancel" },
      { text: "Save", onPress: (value?: string) => input.onSubmit(value ?? "") },
    ],
    "plain-text",
    input.initialNote,
  );
}
