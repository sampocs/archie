import type * as schema from "@/db/schema";
import { cardsWord } from "@/review/labels";

export type TakeKind = "opinion" | "talking_point";
export type TakeRow = typeof schema.takes.$inferSelect;
export type TakeVersionRow = typeof schema.takeVersions.$inferSelect;
type CardRow = typeof schema.cards.$inferSelect;

/** A live take with its versions (oldest first), the version the page shows, and how many live cards it has. */
export type TakeWithVersions = TakeRow & { versions: TakeVersionRow[]; current: TakeVersionRow | null; cardCount: number };
export type TakeFilter = "all" | TakeKind;
export type CleanState = "none" | "cleaning" | "cleaned" | "failed";
export type EditorStart = { kind: TakeKind; title: string; body: string; clean: boolean };

export const TAKE_FILTERS: readonly TakeFilter[] = ["all", "opinion", "talking_point"];
export const TAKE_FILTER_LABELS: Record<TakeFilter, string> = {
  all: "All",
  opinion: "Opinions",
  talking_point: "Talking points",
};
export const TAKE_KIND_LABELS: Record<TakeKind, string> = { opinion: "Opinion", talking_point: "Talking point" };
// Kind kickers borrow two domain colours: Talking point in the Startups blue, Opinion in the History plum.
export const TAKE_KIND_DOMAIN: Record<TakeKind, "Startups" | "History"> = {
  opinion: "History",
  talking_point: "Startups",
};

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** A stored kind; anything this phone doesn't know reads as a talking point, the editor's default. */
export function asTakeKind(kind: string): TakeKind {
  return kind === "opinion" ? "opinion" : "talking_point";
}

/** What a version shows: its body, or the raw text while Clean it up runs. */
export function shownBody(version: Pick<TakeVersionRow, "body" | "rawBody">): string {
  return version.body ?? version.rawBody;
}

export function cleanState(version: Pick<TakeVersionRow, "body" | "cleaned" | "cleanFailed">): CleanState {
  if (version.cleaned !== 1) return "none";
  if (version.body === null) return "cleaning";
  return version.cleanFailed === 1 ? "failed" : "cleaned";
}

/** As the server decides: a first save, a changed body, or Clean it up asked for on a version that wasn't cleaned. */
export function saveMakesVersion(
  current: Pick<TakeVersionRow, "body" | "rawBody" | "cleaned"> | null,
  input: { body: string; clean: boolean },
): boolean {
  if (current === null) return true;
  return input.body !== shownBody(current) || (input.clean && current.cleaned !== 1);
}

/** Live takes with their versions and live card counts, the most recently changed body first. */
export function groupTakes(takes: TakeRow[], versions: TakeVersionRow[], cards: CardRow[]): TakeWithVersions[] {
  const versionsByTake = new Map<string, TakeVersionRow[]>();
  for (const version of versions) {
    versionsByTake.set(version.takeId, [...(versionsByTake.get(version.takeId) ?? []), version]);
  }
  const cardCounts = new Map<string, number>();
  for (const card of cards) {
    if (card.takeId && card.deletedAt === null) cardCounts.set(card.takeId, (cardCounts.get(card.takeId) ?? 0) + 1);
  }

  return takes
    .filter((take) => take.deletedAt === null)
    .map((take) => {
      const own = [...(versionsByTake.get(take.id) ?? [])].sort((a, b) => a.version - b.version);
      const current = own.find((version) => version.version === take.currentVersion) ?? own.at(-1) ?? null;
      return { ...take, versions: own, current, cardCount: cardCounts.get(take.id) ?? 0 };
    })
    .sort((a, b) => Date.parse(takeUpdatedAt(b)) - Date.parse(takeUpdatedAt(a)) || a.id.localeCompare(b.id));
}

/** When the body last changed: the current version's date (a rename or a kind change doesn't count). */
export function takeUpdatedAt(take: TakeWithVersions): string {
  return take.current?.createdAt ?? take.createdAt;
}

export function filterTakes(list: TakeWithVersions[], filter: TakeFilter): TakeWithVersions[] {
  return filter === "all" ? list : list.filter((take) => asTakeKind(take.kind) === filter);
}

export function takeFilterCounts(list: TakeWithVersions[]): Record<TakeFilter, number> {
  const opinions = list.filter((take) => asTakeKind(take.kind) === "opinion").length;
  return { all: list.length, opinion: opinions, talking_point: list.length - opinions };
}

/** "Nov 2" this year, "Nov 2024" before. */
export function takeDate(iso: string, now: Date): string {
  const date = new Date(iso);
  const month = MONTHS[date.getMonth()];
  return date.getFullYear() === now.getFullYear() ? `${month} ${date.getDate()}` : `${month} ${date.getFullYear()}`;
}

/** "Written <first version's date>" until a second version exists, then "Updated <current version's date>". */
export function takeDateLabel(take: TakeWithVersions, now: Date): string {
  if (take.versions.length <= 1) return `Written ${takeDate(take.versions[0]?.createdAt ?? take.createdAt, now)}`;
  return `Updated ${takeDate(takeUpdatedAt(take), now)}`;
}

/** A Takes row's line: "Updated Nov 2 · 3 versions · 4 cards" ("N versions" hidden at 1, the cards at 0). */
export function takeListMeta(take: TakeWithVersions, now: Date): string {
  const parts = [takeDateLabel(take, now)];
  if (take.versions.length > 1) parts.push(`${take.versions.length} versions`);
  if (take.cardCount > 0) parts.push(cardsWord(take.cardCount));
  return parts.join(" · ");
}

/** The take page's mono line: "Updated Nov 2 · version 3". */
export function takePageMeta(take: TakeWithVersions, now: Date): string {
  return `${takeDateLabel(take, now)} · version ${take.current?.version ?? take.currentVersion}`;
}

/** Every version but the one shown, newest first. */
export function earlierVersions(take: TakeWithVersions): TakeVersionRow[] {
  return take.versions.filter((version) => version.id !== take.current?.id).reverse();
}

/** The editor's line under Clean it up. */
export function editorHint(take: TakeWithVersions | null): string {
  if (take === null) return "Saving makes version 1 and writes this take's cards.";
  return `Saving makes version ${take.currentVersion + 1} and rewrites this take's cards.`;
}

/** The editor opens on what the page shows, with Clean it up as this take last had it (off for a new take). */
export function editorStart(take: TakeWithVersions | null): EditorStart {
  if (take === null) return { kind: "talking_point", title: "", body: "", clean: false };
  return {
    kind: asTakeKind(take.kind),
    title: take.title,
    body: take.current ? shownBody(take.current) : "",
    clean: take.current?.cleaned === 1,
  };
}
