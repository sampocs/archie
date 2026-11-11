import { useRouter } from "expo-router";
import { Pressable, View } from "react-native";

import { Card } from "@/theme/components/Card";
import { Text } from "@/theme/components/Text";
import { fontFamily } from "@/theme/type";
import { useTheme } from "@/theme/useTheme";
import { CardHeader } from "@/today/CardHeader";
import { haptic } from "@/ui/haptics";
import { Tappable } from "@/ui/Tappable";

import { briefReadingMinutes, previewLines, storiesInOrder, storyCountLabel, type TodayBrief } from "./brief";

/** Today's brief card: the first headlines and "Read the brief ›", or "writing…" in its header while it is written. */
export function BriefPreviewCard({ state }: { state: NonNullable<TodayBrief> }) {
  const theme = useTheme();
  const router = useRouter();

  if (state.kind === "writing") {
    const newsletters = `${state.newsletters} ${state.newsletters === 1 ? "newsletter" : "newsletters"}`;
    return (
      <Card testID="today-brief-writing">
        <CardHeader label="Your brief" detail={`writing… · ${newsletters}`} />
      </Card>
    );
  }

  const lines = previewLines(state.content);
  const meta = `${storyCountLabel(storiesInOrder(state.content).length)} · ${briefReadingMinutes(state.content)} min`;
  function open(): void {
    haptic("light");
    router.push("/brief");
  }

  return (
    <Tappable testID="today-brief" onPress={open}>
      <Card style={{ gap: 9 }}>
        <CardHeader label="Your brief" detail={meta} testID="today-brief-detail" />
        <View style={{ gap: theme.spacing.xs }}>
          {lines.headlines.map((headline, index) => (
            <Bullet key={index} text={headline} />
          ))}
          {lines.more ? <Bullet text={lines.more} muted /> : null}
        </View>
        <Pressable testID="today-brief-open" onPress={open} hitSlop={8}>
          <Text variant="body" style={{ fontFamily: fontFamily.semibold, fontSize: 14 }}>
            Read the brief ›
          </Text>
        </Pressable>
      </Card>
    </Tappable>
  );
}

function Bullet({ text, muted }: { text: string; muted?: boolean }) {
  const theme = useTheme();
  return (
    <View style={{ flexDirection: "row", gap: theme.spacing.sm }}>
      <Text tone={muted ? "ink3" : "ink"} style={{ fontSize: 14, lineHeight: 14 * 1.45 }}>
        •
      </Text>
      <Text tone={muted ? "ink3" : "ink"} style={{ flex: 1, fontSize: 14, lineHeight: 14 * 1.45 }}>
        {text}
      </Text>
    </View>
  );
}
