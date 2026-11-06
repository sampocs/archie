import { Alert } from "react-native";

export function confirmDeleteTake({ title, onConfirm }: { title: string; onConfirm: () => void }): void {
  Alert.alert(`Delete “${title}”?`, "Its versions and cards go with it.", [
    { text: "Cancel", style: "cancel" },
    { text: "Delete", style: "destructive", onPress: onConfirm },
  ]);
}
