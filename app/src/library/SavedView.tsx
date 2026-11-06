import { useRouter } from "expo-router";
import { Pressable, View } from "react-native";

import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { slugify } from "@/topics/topicName";
import { GroupedList } from "@/ui/GroupedList";
import { haptic } from "@/ui/haptics";

import { favoriteDomains } from "./favorites";
import type { LibraryData } from "./join";

const DOMAIN_DOT = 10;

/** Library's Saved mode: the starred items, one row per domain (collections arrive in a later piece). */
export function SavedView({ data }: { data: LibraryData }) {
  const theme = useTheme();
  const router = useRouter();
  const groups = favoriteDomains(data.sources);
  const total = groups.reduce((sum, group) => sum + group.count, 0);

  return (
    <View testID="saved-view" style={{ gap: theme.spacing.md }}>
      {groups.length === 0 ? (
        <View style={{ alignItems: "center", paddingVertical: theme.spacing.xl }}>
          <Text testID="saved-empty" tone="ink2" style={{ textAlign: "center" }}>
            Star items to keep them here, or save something just for fun to a collection.
          </Text>
        </View>
      ) : (
        <GroupedList testID="saved-favorites" title={`Favorites · ${total}`}>
          {groups.map((group) => (
            <Pressable
              key={group.domain}
              testID={`favorites-domain-${slugify(group.domain)}`}
              onPress={() => {
                haptic("light");
                router.push({ pathname: "/favorites/[domain]", params: { domain: group.domain } });
              }}
              style={{ flexDirection: "row", alignItems: "center", gap: theme.spacing.sm, paddingVertical: theme.spacing.md }}
            >
              <View style={{ width: DOMAIN_DOT, height: DOMAIN_DOT, borderRadius: DOMAIN_DOT / 2, backgroundColor: theme.domains[group.domain] }} />
              <View style={{ flex: 1 }}>
                <Text variant="headline">{group.domain}</Text>
                <Text variant="secondary" tone="ink3" numberOfLines={1}>
                  {group.newestTitles.join(" · ")}
                </Text>
              </View>
              <Text tone="ink3">{`${group.count} ›`}</Text>
            </Pressable>
          ))}
        </GroupedList>
      )}
    </View>
  );
}
