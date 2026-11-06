import { useLocalSearchParams, useRouter } from "expo-router";
import { View } from "react-native";

import { setFavorite } from "@/db/actions";
import { db } from "@/db/client";
import { domainFavorites, favoriteMeta } from "@/library/favorites";
import { SwipeRow, type SwipeAction } from "@/library/SwipeRow";
import { useLibraryData } from "@/library/useLibraryData";
import { requestSync } from "@/sync/useSync";
import { Screen } from "@/theme/components/Screen";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { asDomain } from "@/topics/domains";
import { GroupedList } from "@/ui/GroupedList";
import { Kicker } from "@/ui/Kicker";
import { SourceRow } from "@/ui/SourceRow";

/** The starred items of one domain, newest star first; swipe to unstar. */
export default function FavoritesScreen() {
  const router = useRouter();
  const theme = useTheme();
  const domain = asDomain(useLocalSearchParams<{ domain: string }>().domain ?? null);
  const favorites = domainFavorites(useLibraryData().sources, domain);

  return (
    <Screen title={domain} onBack={router.back}>
      <View testID="favorites-page" style={{ gap: theme.spacing.md }}>
        <Kicker domain={domain} label="Favorites" />
        {favorites.length === 0 ? (
          <Text tone="ink2">{`No favorites in ${domain} yet.`}</Text>
        ) : (
          <GroupedList>
            {favorites.map((source) => {
              const unstar: SwipeAction = {
                key: "unstar",
                label: "Unstar",
                tone: "neutral",
                testID: `favorite-unstar-${source.id}`,
                onPress: () => {
                  setFavorite(db, source.id, false);
                  requestSync();
                },
              };

              return (
                <SwipeRow key={source.id} actions={[unstar]}>
                  <SourceRow
                    source={source}
                    testID={`favorite-row-${source.id}`}
                    kickerSuffix={source.topic?.name}
                    meta={favoriteMeta({ kind: source.kind, favoritedAt: source.favoritedAt! })}
                  />
                </SwipeRow>
              );
            })}
          </GroupedList>
        )}
      </View>
    </Screen>
  );
}
