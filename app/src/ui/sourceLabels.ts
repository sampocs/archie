/** Display strings for a source's badge and byline, shared by the Library row and the source page. */

import { MONTHS, recentDayLabel, WEEKDAYS } from "@/today/todayLabels";

type BylineSource = { kind: string; url: string; sender: string | null };

/** Who a source came from: a newsletter's sender, otherwise the link's site. */
export function sourceByline(source: BylineSource): string {
  if (source.kind === "newsletter") return source.sender ?? "Newsletter";
  if (!URL.canParse(source.url)) return source.url;
  return new URL(source.url).hostname.replace(/^www\./, "");
}

export function kindLabel(kind: string): string {
  if (kind === "podcast") return "Podcast";
  if (kind === "youtube") return "YouTube";
  if (kind === "article") return "Article";
  if (kind === "x") return "X post";
  if (kind === "newsletter") return "Newsletter";
  return "Link";
}

/** The one-line meta under a row's title: "Podcast · open.spotify.com". */
export function sourceMeta(source: BylineSource): string {
  return `${kindLabel(source.kind)} · ${sourceByline(source)}`;
}

/** When a newsletter was sent: its Date header, else (from an older server) when it arrived. */
export function sentDate(source: { createdAt: string; publishedAt: string | null }): Date {
  return new Date(source.publishedAt ?? source.createdAt);
}

/**
 * The item page's byline with its date: a newsletter's send day ("Morning Brew · Wed, Nov 4"), otherwise when it was
 * added ("open.spotify.com · Added Mon").
 */
export function datedByline(
  source: BylineSource & { createdAt: string; publishedAt: string | null },
  now: Date,
): string {
  if (source.kind === "newsletter") {
    const sent = sentDate(source);
    return `${sourceByline(source)} · ${WEEKDAYS[sent.getDay()]}, ${MONTHS[sent.getMonth()]} ${sent.getDate()}`;
  }
  return `${sourceByline(source)} · Added ${recentDayLabel(source.createdAt, now)}`;
}

/** The item page's badge: where the item is. A briefed newsletter still reads as the inbox. */
export function itemBadge(state: string): "Inbox" | "Queued" | "Done" {
  if (state === "queued") return "Queued";
  if (state === "consumed") return "Done";
  return "Inbox";
}
