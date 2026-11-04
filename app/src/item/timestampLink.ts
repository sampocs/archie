const CLOCK = /^(?:(\d{1,2}):)?(\d{1,2}):(\d{2})$/;
const SPOTIFY_EPISODE = /^\/(?:intl-[a-z]+\/)?episode\//;

/** "12:14" → 734, "1:02:03" → 3723; anything else is null. */
export function timestampSeconds(timestamp: string): number | null {
  const match = CLOCK.exec(timestamp.trim());
  if (!match) return null;

  const [, hours, minutes, seconds] = match;
  return Number(hours ?? 0) * 3600 + Number(minutes) * 60 + Number(seconds);
}

/** Where tapping a timestamp chip goes: the source opened at that moment where its player supports a `t` parameter. */
export function timestampUrl(source: { kind: string; url: string }, timestamp: string): string {
  const seconds = timestampSeconds(timestamp);
  if (seconds === null || !URL.canParse(source.url)) return source.url;

  const url = new URL(source.url);
  const isSpotifyEpisode = url.hostname === "open.spotify.com" && SPOTIFY_EPISODE.test(url.pathname);
  if (source.kind !== "youtube" && !isSpotifyEpisode) return source.url;

  url.searchParams.set("t", String(seconds));
  return url.toString();
}
