import { Pressable } from "react-native";

import { retrySource } from "@/db/actions";
import { db } from "@/db/client";
import { requestSync } from "@/sync/useSync";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";

type ProcessingLineProps = {
  source: { id: string; processing: string; processingError: string | null };
};

/** The pipeline status under a source's title; shared by the Library row and the source page. */
export function ProcessingLine({ source }: ProcessingLineProps) {
  const theme = useTheme();

  if (source.processing === "pending" || source.processing === "processing") {
    return (
      <Text testID={`source-processing-${source.id}`} variant="secondary" tone="ink3">
        Processing…
      </Text>
    );
  }
  if (source.processing === "unsupported") {
    return (
      <Text variant="secondary" tone="ink3">
        {source.processingError ?? "Not processed yet"}
      </Text>
    );
  }
  if (source.processing !== "failed") return null;

  async function retry(): Promise<void> {
    await retrySource(db, source.id);
    requestSync();
  }

  return (
    <>
      <Text variant="secondary" style={{ color: theme.signals.missed }}>
        {source.processingError ?? "Processing failed"}
      </Text>
      <Pressable testID={`source-retry-${source.id}`} onPress={retry} hitSlop={8}>
        <Text variant="secondary" style={{ textDecorationLine: "underline" }}>
          Retry
        </Text>
      </Pressable>
    </>
  );
}
