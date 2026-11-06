import { View } from "react-native";

import { Markdown } from "@/ui/Markdown";

/** A take's text as markdown (headings, bullets, emphasis), read-only. */
export function TakeBody({ markdown, testID }: { markdown: string; testID?: string }) {
  return (
    <View testID={testID}>
      <Markdown text={markdown} />
    </View>
  );
}
