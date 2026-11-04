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
  unread?: boolean;
  testID?: string;
};

const UNREAD_DOT = { light: "#3D7BF2", dark: "#6EA1FF" } as const;
const DOT_SIZE = 8;

/** Square (or round) artwork; a domain-colored monogram stands in when there is no image or it fails to load. */
export function ArtworkTile({ imageUrl, domain, monogram, size, circle, unread, testID }: ArtworkTileProps) {
  const theme = useTheme();
  const [failed, setFailed] = useState(false);
  const showImage = imageUrl !== null && !failed;

  useEffect(() => setFailed(false), [imageUrl]);

  const shape = { width: size, height: size, borderRadius: circle ? size / 2 : Math.round(size * 0.22) };

  return (
    <View testID={testID} style={{ width: size, height: size }}>
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
          <Text variant="headline" style={{ color: "#FFFFFF", fontSize: size * 0.42 }}>
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
            backgroundColor: UNREAD_DOT[theme.scheme],
          }}
        />
      ) : null}
    </View>
  );
}
