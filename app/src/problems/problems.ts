export type Problem = {
  kind: string;
  key: string;
  title: string;
  detail: string;
  /** ISO time the problem began. */
  since: string;
};

/** The phone says the server is unreachable once it hasn't answered a sync for this long. */
export const UNREACHABLE_AFTER_MS = 24 * 60 * 60 * 1000;

const UNREACHABLE_KIND = "server_unreachable";
const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;

/** The `/problems` body as rows; anything malformed is dropped. */
export function parseProblems(body: unknown): Problem[] {
  const problems = (body as { problems?: unknown } | null)?.problems;
  if (!Array.isArray(problems)) return [];
  return problems.flatMap((row) => {
    const item = (row ?? {}) as Record<string, unknown>;
    const { kind, key, title, detail, since } = item;
    if (typeof kind !== "string" || typeof key !== "string" || typeof title !== "string") return [];
    if (typeof detail !== "string" || typeof since !== "string" || Number.isNaN(Date.parse(since))) return [];
    return [{ kind, key, title, detail, since }];
  });
}

/** "just now", "5 min ago", "3 hours ago", "2 days ago". */
export function agoLabel(iso: string, now: Date): string {
  const elapsed = Math.max(0, now.getTime() - Date.parse(iso));
  if (elapsed < MINUTE_MS) return "just now";
  if (elapsed < HOUR_MS) return `${Math.floor(elapsed / MINUTE_MS)} min ago`;
  if (elapsed < DAY_MS) return plural(Math.floor(elapsed / HOUR_MS), "hour");
  return plural(Math.floor(elapsed / DAY_MS), "day");
}

function plural(count: number, unit: string): string {
  return `${count} ${unit}${count === 1 ? "" : "s"} ago`;
}

/** "1 thing needs a look" / "3 things need a look". */
export function bannerText(count: number): string {
  return count === 1 ? "1 thing needs a look" : `${count} things need a look`;
}

/**
 * The server's problems plus the phone's own: nothing at all when offline (an unreachable server is expected there),
 * and an unreachable-server problem when online and the last sync that reached it is over a day old. A phone that
 * has never reached the server has no last contact to measure from, so it adds nothing. The stored contact time
 * comes from a previous app run, so nothing is added until a sync has been attempted this run (`syncAttempted`);
 * otherwise the problem would flash on launch until the first sync stamps a fresh time.
 */
export function mergeProblems(input: {
  serverProblems: Problem[];
  lastServerContactAt: number | null;
  online: boolean;
  syncAttempted: boolean;
  now: Date;
}): Problem[] {
  if (!input.online) return [];

  const last = input.lastServerContactAt;
  if (!input.syncAttempted || last === null || input.now.getTime() - last <= UNREACHABLE_AFTER_MS) return input.serverProblems;

  const since = new Date(last).toISOString();
  const unreachable: Problem = {
    kind: UNREACHABLE_KIND,
    key: UNREACHABLE_KIND,
    title: "Can't reach Archie's server",
    detail: `Last synced ${agoLabel(since, input.now)}`,
    since,
  };
  return [...input.serverProblems, unreachable];
}
