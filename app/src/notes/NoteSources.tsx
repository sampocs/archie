import * as WebBrowser from "expo-web-browser";
import { Pressable, View } from "react-native";

import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";

type NoteSource = { url: string; title: string };

function hostOf(url: string): string {
  return URL.canParse(url) ? new URL(url).hostname.replace(/^www\./, "") : url;
}

/** The pages a note's write-up drew on: host above title, each opening in the in-app browser. */
export function NoteSources({ sources }: { sources: NoteSource[] }) {
  const theme = useTheme();
  if (sources.length === 0) return null;

  return (
    <View style={{ gap: theme.spacing.md }}>
      <Text variant="kicker" tone="ink2">
        Sources
      </Text>
      {sources.map((source, index) => (
        <Pressable
          key={source.url}
          testID={`note-source-${index}`}
          onPress={() => void WebBrowser.openBrowserAsync(source.url)}
          style={{ gap: theme.spacing.xs }}
        >
          <Text variant="monoLabel" tone="ink3">
            {hostOf(source.url)}
          </Text>
          <Text variant="readingBody">{source.title}</Text>
        </Pressable>
      ))}
    </View>
  );
}
