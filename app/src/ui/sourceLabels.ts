/** Display strings for a source's state chip and byline, shared by the Library row and the source page. */

type BylineSource = { kind: string; url: string; sender: string | null };

/** Who a source came from: a newsletter's sender, otherwise the link's site. */
export function sourceByline(source: BylineSource): string {
  if (source.kind === "newsletter") return source.sender ?? "Newsletter";
  if (!URL.canParse(source.url)) return source.url;
  return new URL(source.url).hostname.replace(/^www\./, "");
}

export function stateLabel(state: string): string {
  if (state === "inbox") return "Inbox";
  if (state === "queued") return "Queued";
  if (state === "consumed") return "Done";
  return state.charAt(0).toUpperCase() + state.slice(1);
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
