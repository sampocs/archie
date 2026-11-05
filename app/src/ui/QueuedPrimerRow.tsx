import { useRouter } from "expo-router";
import { ReactNode } from "react";

import type { LibrarySource } from "@/library/join";
import { readingMinutes } from "@/library/primer";

import { ItemRow } from "./ItemRow";
import { PRIMER_MONOGRAM } from "./monogram";

type QueuedPrimerRowProps = { source: LibrarySource; end?: ReactNode; testID?: string };

/** A source's primer as its own queue entry: a ◆ tile in the item's domain color; tapping opens the primer. */
export function QueuedPrimerRow({ source, end, testID }: QueuedPrimerRowProps) {
  const router = useRouter();

  return (
    <ItemRow
      testID={testID}
      artwork={{ imageUrl: null, domain: source.domain, monogram: PRIMER_MONOGRAM }}
      kicker={{ domain: source.domain, suffix: "Primer" }}
      title={`Primer: ${source.title ?? source.url}`}
      meta={source.primerWords === null ? "Writing primer…" : `${readingMinutes(source.primerWords)} min read`}
      end={end}
      onPress={() => router.push({ pathname: "/primer/[id]", params: { id: source.id } })}
    />
  );
}
