import { useRouter } from "expo-router";
import { Pressable, View } from "react-native";

import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { haptic } from "@/ui/haptics";
import { Kicker } from "@/ui/Kicker";

import { asTakeKind, TAKE_KIND_DOMAIN, TAKE_KIND_LABELS, takeListMeta, type TakeWithVersions } from "./takes";

const TILE_SIZE = 46;

/** One take in Library's Takes list: a quote tile, its kind, title and date line. Opens the take page. */
export function TakeRow({ take, now }: { take: TakeWithVersions; now: Date }) {
  const theme = useTheme();
  const router = useRouter();
  const kind = asTakeKind(take.kind);

  function open(): void {
    haptic("light");
    router.push({ pathname: "/take/[id]", params: { id: take.id } });
  }

  return (
    <Pressable
      testID={`take-row-${take.id}`}
      onPress={open}
      style={{ flexDirection: "row", alignItems: "center", gap: theme.spacing.md, paddingVertical: theme.spacing.md }}
    >
      <View
        style={{
          width: TILE_SIZE,
          height: TILE_SIZE,
          borderRadius: 10,
          backgroundColor: theme.colors.press,
          borderWidth: 1,
          borderColor: "rgba(0,0,0,0.05)",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <Text tone="ink2" style={{ fontFamily: "Georgia", fontSize: 24 }}>
          ❝
        </Text>
      </View>
      <View style={{ flex: 1, gap: 2 }}>
        <Kicker domain={TAKE_KIND_DOMAIN[kind]} label={TAKE_KIND_LABELS[kind]} />
        <Text variant="headline" numberOfLines={2}>
          {take.title}
        </Text>
        <Text variant="secondary" tone="ink3" numberOfLines={1}>
          {takeListMeta(take, now)}
        </Text>
      </View>
    </Pressable>
  );
}
