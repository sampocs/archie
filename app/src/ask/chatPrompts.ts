import { Alert } from "react-native";

import { MAX_CHAT_TITLE_LENGTH } from "@/db/actions";

/** Asks for a chat's new name with the system prompt; a blank answer does nothing, a long one is cut. */
export function promptChatName(input: { currentTitle: string; onSubmit: (title: string) => void }): void {
  Alert.prompt(
    "Rename chat",
    undefined,
    [
      { text: "Cancel", style: "cancel" },
      {
        text: "Rename",
        onPress: (value?: string) => {
          const title = Array.from(value?.trim() ?? "")
            .slice(0, MAX_CHAT_TITLE_LENGTH)
            .join("");
          if (title) input.onSubmit(title);
        },
      },
    ],
    "plain-text",
    input.currentTitle,
  );
}

/** Asks before deleting, saying that what was saved from the chat outlives it. */
export function confirmDeleteChat(onConfirm: () => void): void {
  Alert.alert("Delete this chat?", "Cards and Library items you saved from it stay.", [
    { text: "Cancel", style: "cancel" },
    { text: "Delete", style: "destructive", onPress: onConfirm },
  ]);
}
