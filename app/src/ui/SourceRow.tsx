import { useRouter } from "expo-router";
import { ReactNode } from "react";

import type { LibrarySource } from "@/library/join";
import { statusTag } from "@/library/visibility";

import { ItemRow } from "./ItemRow";
import { monogramFor } from "./monogram";
import { sourceMeta } from "./sourceLabels";

type SourceRowProps = {
  source: LibrarySource;
  end?: ReactNode;
  meta?: string;
  /** Appended to the kicker, e.g. the topic name on the favorites page. */
  kickerSuffix?: string;
  testID?: string;
  onPress?: () => void;
};

/** An `ItemRow` for a source; tapping opens its page unless `onPress` says otherwise. */
export function SourceRow({ source, end, meta, kickerSuffix, testID, onPress }: SourceRowProps) {
  const router = useRouter();

  return (
    <ItemRow
      testID={testID}
      artwork={{
        imageUrl: source.imageUrl,
        domain: source.domain,
        monogram: monogramFor(source),
        circle: source.kind === "x",
        unread: statusTag(source) === "Unread",
      }}
      kicker={{ domain: source.domain, suffix: kickerSuffix, starred: source.favoritedAt !== null }}
      title={source.title ?? source.url}
      meta={meta ?? sourceMeta(source)}
      end={end}
      onPress={onPress ?? (() => router.push({ pathname: "/source/[id]", params: { id: source.id } }))}
    />
  );
}
