import { MONTHS } from "@/today/todayLabels";
import { asDomain, DOMAINS, type DomainName } from "@/topics/domains";
import { kindLabel } from "@/ui/sourceLabels";

import type { LibrarySource } from "./join";

export const FAVORITE_PREVIEW_TITLES = 2;

export type FavoriteDomain = { domain: DomainName; count: number; newestTitles: string[] };

/** The starred sources of one domain, newest star first. A source with no domain yet (unfiled, or filing failed) counts as Other, as its row's kicker reads. */
export function domainFavorites(sources: LibrarySource[], domain: DomainName): LibrarySource[] {
  return sources
    .filter((source) => source.favoritedAt !== null && asDomain(source.domain) === domain)
    .sort((first, second) => (second.favoritedAt ?? "").localeCompare(first.favoritedAt ?? ""));
}

/** Saved's Favorites rows: one per domain with stars, biggest first, ties in `DOMAINS` order. */
export function favoriteDomains(sources: LibrarySource[]): FavoriteDomain[] {
  const groups = DOMAINS.map((domain): FavoriteDomain => {
    const favorites = domainFavorites(sources, domain);
    return {
      domain,
      count: favorites.length,
      newestTitles: favorites.slice(0, FAVORITE_PREVIEW_TITLES).map((source) => source.title ?? source.url),
    };
  });

  // Array.sort is stable, so equal counts keep DOMAINS order.
  return groups.filter((group) => group.count > 0).sort((first, second) => second.count - first.count);
}

/** The favorites page's row meta: "X post · starred Nov 3". */
export function favoriteMeta(source: { kind: string; favoritedAt: string }): string {
  const starred = new Date(source.favoritedAt);
  return `${kindLabel(source.kind)} · starred ${MONTHS[starred.getMonth()]} ${starred.getDate()}`;
}
