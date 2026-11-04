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
  testID?: string;
  onPress?: () => void;
};

/** An `ItemRow` for a source; tapping opens its page unless `onPress` says otherwise. */
export function SourceRow({ source, end, meta, testID, onPress }: SourceRowProps) {
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
      kicker={{ domain: source.domain }}
      title={source.title ?? source.url}
      meta={meta ?? sourceMeta(source)}
      end={end}
      onPress={onPress ?? (() => router.push({ pathname: "/source/[id]", params: { id: source.id } }))}
    />
  );
}
