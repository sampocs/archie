// Spike: can a Cloudflare Worker fetch YouTube transcripts the way youtube-transcript-api does?
// Steps per video: (1) watch page -> INNERTUBE key, (2) InnerTube player (ANDROID client) -> caption tracks,
// (3) timedtext URL -> transcript XML. Each step's HTTP status / error is recorded.
// GET /        -> latest stored results as JSON
// GET /run     -> run now, store, and return results
// Cron (every 6h) -> run + store.

const VIDEOS = [
  ["ugvHCXCOmm4", "Lex x Dario, 5.2h, human captions"],
  ["y0YkGWKT0gI", "Odd Lots, 40m, human captions"],
  ["LPZh9BOjkQs", "3Blue1Brown LLMs, 8m, human captions"],
  ["0lJKucu6HJc", "Altman startup talk, 16m, auto captions"],
  ["iClsnZ1KYSk", "Bankless Tom Lee, 63m, auto captions"],
  ["e0gVE3YxZs8", "Powell 60s, auto captions"],
  ["SlpcNYFuuWw", "Bitcoin livestream, captions disabled"],
];

const ANDROID_CONTEXT = {
  client: { clientName: "ANDROID", clientVersion: "20.10.38", androidSdkVersion: 30, hl: "en", gl: "US" },
};
const ANDROID_UA = "com.google.android.youtube/20.10.38 (Linux; U; Android 11) gzip";
const BROWSER_UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36";

async function fetchTranscript(videoId) {
  const result = { videoId, ok: false, step: "watch_page", status: null, words: 0, playability: null, error: null, ms: 0 };
  const started = Date.now();
  try {
    // Step 1: watch page, to get the InnerTube API key (what youtube-transcript-api does).
    const watch = await fetch(`https://www.youtube.com/watch?v=${videoId}`, {
      headers: { "User-Agent": BROWSER_UA, "Accept-Language": "en-US", Cookie: "CONSENT=YES+1" },
    });
    result.status = watch.status;
    const html = await watch.text();
    result.watchHtmlHasRecaptcha = html.includes('class="g-recaptcha"');
    const pageKey = /"INNERTUBE_API_KEY":\s*"([a-zA-Z0-9_-]+)"/.exec(html)?.[1];
    result.watchPageBlocked = !pageKey;
    if (!pageKey) {
      result.watchError = result.watchHtmlHasRecaptcha ? "IpBlocked (recaptcha page)" : "no INNERTUBE_API_KEY in watch page";
    }
    // Without the watch page's key, keep going keyless to see whether the player endpoint is blocked too.
    const keyParam = pageKey ? `?key=${pageKey}` : "";

    // Step 2: InnerTube player endpoint as the Android client, which returns caption track URLs.
    result.step = "innertube_player";
    const player = await fetch(`https://www.youtube.com/youtubei/v1/player${keyParam}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "User-Agent": ANDROID_UA },
      body: JSON.stringify({ context: ANDROID_CONTEXT, videoId }),
    });
    result.status = player.status;
    if (!player.ok) {
      result.error = `player HTTP ${player.status}: ${(await player.text()).slice(0, 200)}`;
      return result;
    }
    const data = await player.json();
    result.playability = `${data.playabilityStatus?.status}: ${data.playabilityStatus?.reason ?? ""}`.trim();
    const tracks = data.captions?.playerCaptionsTracklistRenderer?.captionTracks;
    if (!tracks?.length) {
      result.error = "no caption tracks in player response";
      return result;
    }
    const track = tracks.find((candidate) => candidate.languageCode === "en") ?? tracks[0];
    result.trackKind = track.kind ?? "manual";

    // Step 3: timedtext URL (srv3 format stripped, as the library does).
    result.step = "timedtext";
    const timed = await fetch(track.baseUrl.replace("&fmt=srv3", ""), { headers: { "User-Agent": ANDROID_UA } });
    result.status = timed.status;
    const xml = await timed.text();
    if (!timed.ok || !xml.length) {
      result.error = `timedtext HTTP ${timed.status}, ${xml.length} bytes`;
      return result;
    }
    result.words = xml.replace(/<[^>]+>/g, " ").split(/\s+/).filter(Boolean).length;
    result.ok = result.words > 0;
    result.step = "done";
  } catch (error) {
    result.error = `${error.name}: ${error.message}`;
  } finally {
    result.ms = Date.now() - started;
  }
  return result;
}

async function runAll(env, trigger) {
  const trace = await fetch("https://www.cloudflare.com/cdn-cgi/trace").then((response) => response.text()).catch(() => "");
  const colo = /colo=(\w+)/.exec(trace)?.[1] ?? null;
  const results = [];
  for (const [videoId, label] of VIDEOS) {
    results.push({ label, ...(await fetchTranscript(videoId)) });
  }
  const run = {
    at: new Date().toISOString(),
    trigger,
    colo,
    okCount: results.filter((entry) => entry.ok).length,
    total: results.length,
    results,
  };
  await env.RESULTS.put(`run:${run.at}`, JSON.stringify(run));
  await env.RESULTS.put("latest", JSON.stringify(run));
  return run;
}

export default {
  async fetch(request, env) {
    const path = new URL(request.url).pathname;
    const run = path === "/run" ? await runAll(env, "http") : JSON.parse((await env.RESULTS.get("latest")) ?? "null");
    return Response.json(run, { headers: { "Cache-Control": "no-store" } });
  },
  async scheduled(event, env, ctx) {
    ctx.waitUntil(runAll(env, "cron"));
  },
};
