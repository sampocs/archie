import type * as schema from "@/db/schema";
import { MONTHS } from "@/today/todayLabels";

export type CollectionRow = typeof schema.collections.$inferSelect;
export type CollectionItemRow = typeof schema.collectionItems.$inferSelect;
export type CollectionWithItems = CollectionRow & { items: CollectionItemRow[] };

export const MOSAIC_SIZE = 4;

/** Live collections in tile order, each with its live posts newest first. */
export function groupCollections(collections: CollectionRow[], items: CollectionItemRow[]): CollectionWithItems[] {
  const live = collections
    .filter((collection) => collection.deletedAt === null)
    .sort((a, b) => a.position - b.position || a.createdAt.localeCompare(b.createdAt));
  const newestFirst = items
    .filter((item) => item.deletedAt === null)
    .sort((a, b) => b.createdAt.localeCompare(a.createdAt));
  return live.map((collection) => ({
    ...collection,
    items: newestFirst.filter((item) => item.collectionId === collection.id),
  }));
}

/** The tile's 2×2 mosaic: the four newest thumbnails, padded with null (a neutral cell). */
export function mosaicImages(collection: CollectionWithItems): (string | null)[] {
  const images = collection.items.map((item) => item.imageUrl).filter((url): url is string => url !== null);
  const newest = images.slice(0, MOSAIC_SIZE);
  return [...newest, ...Array<null>(MOSAIC_SIZE - newest.length).fill(null)];
}

export function savedCountLabel(count: number): string {
  return `${count} saved`;
}

/** The link's host without "www.", or the URL itself when it can't be parsed. */
export function postSiteName(url: string): string {
  if (!URL.canParse(url)) return url;
  return new URL(url).hostname.replace(/^www\./, "");
}

export function isVideo(item: { kind: string; durationSeconds: number | null }): boolean {
  return item.kind === "youtube" || item.durationSeconds !== null;
}

/** Where a post is from: "X video", "X post", "YouTube", or the site. */
export function postSourceLabel(item: { kind: string; url: string; durationSeconds: number | null }): string {
  if (item.kind === "x") return item.durationSeconds !== null ? "X video" : "X post";
  if (item.kind === "youtube") return "YouTube";
  return postSiteName(item.url);
}

/** "@BearsFilmRoom · X video"; just the source when the author isn't known. */
export function postByline(item: {
  kind: string;
  url: string;
  author: string | null;
  durationSeconds: number | null;
}): string {
  return [item.author, postSourceLabel(item)].filter(Boolean).join(" · ");
}

/** "0:48", "3:12", "1:02:05". */
export function formatDuration(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = String(seconds % 60).padStart(2, "0");
  return hours > 0 ? `${hours}:${String(minutes).padStart(2, "0")}:${secs}` : `${minutes}:${secs}`;
}

/** The date a post was saved, as the feed shows it: "Nov 3". */
export function savedDate(createdAt: string): string {
  const saved = new Date(createdAt);
  return `${MONTHS[saved.getMonth()]} ${saved.getDate()}`;
}

/** The collection a save preselects: the last one used if it still exists, else the newest, else none. */
export function defaultCollectionId(collections: { id: string }[], lastUsedId: string | null): string | null {
  if (lastUsedId && collections.some((collection) => collection.id === lastUsedId)) return lastUsedId;
  return collections.at(-1)?.id ?? null;
}
