import { ScrollView } from "react-native";

import { useTheme } from "@/theme/useTheme";
import { Text } from "@/theme/components/Text";
import { BottomSheet } from "@/ui/BottomSheet";
import { Markdown } from "@/ui/Markdown";
import { longDate } from "@/ui/sourceLabels";

// `editedAt` is a Bear note's last edit; null for an imported book's notes, which have no Bear byline.
type OriginalNoteSheetProps = {
  markdown: string;
  editedAt: string | null;
  title?: string;
  visible: boolean;
  onClose: () => void;
};

/** The note as the user wrote it (it is synced, so this works offline), like the newsletter's full-email sheet. */
export function OriginalNoteSheet({ markdown, editedAt, title, visible, onClose }: OriginalNoteSheetProps) {
  const theme = useTheme();

  return (
    <BottomSheet visible={visible} onClose={onClose} testID="original-note-sheet">
      <Text variant="headline">{title ?? "Your original note"}</Text>
      {editedAt ? (
        <Text variant="secondary" tone="ink2" style={{ marginBottom: theme.spacing.sm }}>
          {`From Bear · last edited ${longDate(editedAt)}`}
        </Text>
      ) : null}
      <ScrollView style={{ maxHeight: 520 }}>
        <Markdown text={markdown} />
      </ScrollView>
    </BottomSheet>
  );
}
