import type { LibrarySource } from "./join";

/** Everything local search looks at, lower-cased: title, sender, domain, topic name, gist and key ideas. */
export function searchText(source: LibrarySource): string {
  const parts = [
    source.title,
    source.sender,
    source.domain,
    source.topic?.name,
    source.summary?.gist,
    ...(source.summary?.key_ideas.map((item) => item.idea) ?? []),
  ];
  return parts
    .filter((part): part is string => Boolean(part))
    .join("\n")
    .toLowerCase();
}

/** Every whitespace-separated term of the query appears somewhere in the text; an empty query matches all. */
export function matchesQuery(text: string, query: string): boolean {
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
  return terms.every((term) => text.includes(term));
}
