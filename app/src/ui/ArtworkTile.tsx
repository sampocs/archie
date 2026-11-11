import { Image } from "expo-image";
import { useEffect, useState } from "react";
import { View } from "react-native";

import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { asDomain } from "@/topics/domains";

export type ArtworkTileProps = {
  imageUrl: string | null;
  domain: string | null;
  monogram: string;
  size: number;
  circle?: boolean;
  /** A 2:3 book cover: `size` is the height, and the width is two thirds of it. */
  portrait?: boolean;
  unread?: boolean;
  testID?: string;
};

const DOT_SIZE = 8;

/**
 * Square (or round, or a portrait book cover) artwork; a domain-colored monogram stands in when there is no image or
 * it fails to load.
 */
export function ArtworkTile({ imageUrl, domain, monogram, size, circle, portrait, unread, testID }: ArtworkTileProps) {
  const theme = useTheme();
  const [failed, setFailed] = useState(false);
  const showImage = imageUrl !== null && !failed;

  useEffect(() => setFailed(false), [imageUrl]);

  const width = portrait ? Math.round((size * 2) / 3) : size;
  // A cover keeps the small radius of a printed book; other tiles round like app icons.
  const borderRadius = circle ? size / 2 : portrait ? Math.round(size * 0.06) : Math.round(size * 0.22);
  const shape = { width, height: size, borderRadius };

  return (
    <View testID={testID} style={{ width, height: size }}>
      {showImage ? (
        <Image
          source={{ uri: imageUrl }}
          cachePolicy="disk"
          onError={() => setFailed(true)}
          style={[shape, { backgroundColor: theme.colors.press }]}
        />
      ) : (
        <View
          style={[
            shape,
            { backgroundColor: theme.domains[asDomain(domain)], alignItems: "center", justifyContent: "center" },
          ]}
        >
          <Text variant="headline" style={{ color: theme.colors.onDomain, fontSize: width * 0.42 }}>
            {monogram}
          </Text>
        </View>
      )}
      {unread ? (
        <View
          testID={testID ? `${testID}-unread` : undefined}
          style={{
            position: "absolute",
            top: -2,
            left: -2,
            width: DOT_SIZE,
            height: DOT_SIZE,
            borderRadius: DOT_SIZE / 2,
            backgroundColor: theme.colors.unread,
          }}
        />
      ) : null}
    </View>
  );
}
