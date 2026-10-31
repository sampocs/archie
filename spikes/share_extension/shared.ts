import type { InitialProps } from "expo-share-extension";

export type Payload = {
  rawUrl?: string;
  rawText?: string;
  // Some apps share only text with the link buried inside it, so pull the first URL out of either field
  url?: string;
  source: string;
  // Only Safari shares carry this: the page text as the logged-in user sees it, past paywalls and bot-blocking
  page?: PageCapture;
};

export type PageCapture = {
  title: string;
  words: number;
  // Taken from the middle so it shows real article body, not the teaser a paywall leaves visible
  excerpt: string;
};

type PreprocessingResults = { url?: string; title?: string; text?: string };

export type ProbeResult = {
  status?: number;
  millis: number;
  title?: string;
  error?: string;
};

export type SharedRecord = {
  receivedAt: string;
  payload: Payload;
  probe: ProbeResult | null;
};

const URL_PATTERN = /https?:\/\/[^\s]+/;
const TRAILING_PUNCTUATION = /[).,!?"'\]]+$/;
const PROBE_TIMEOUT_MS = 10_000;
const EXCERPT_CHARS = 240;
const SOURCES: [RegExp, string][] = [
  [/open\.spotify\.com|spotify\.link/, "spotify"],
  [/podcasts\.apple\.com/, "apple podcasts"],
  [/(^|\.)(x|twitter)\.com/, "x"],
  [/youtube\.com|youtu\.be/, "youtube"],
];

export function describePayload(props: InitialProps): Payload {
  const preprocessed = props.preprocessingResults as PreprocessingResults | undefined;
  const url =
    props.url ?? preprocessed?.url ?? props.text?.match(URL_PATTERN)?.[0]?.replace(TRAILING_PUNCTUATION, "");
  const host = url ? safeHost(url) : undefined;
  const source = host ? (SOURCES.find(([pattern]) => pattern.test(host))?.[1] ?? `web (${host})`) : "text only";
  const page = preprocessed?.text ? capturePage(preprocessed.title ?? "", preprocessed.text) : undefined;
  return { rawUrl: props.url, rawText: props.text, url, source, page };
}

function capturePage(title: string, text: string): PageCapture {
  const flat = text.replace(/\s+/g, " ").trim();
  const middle = Math.max(0, Math.floor(flat.length / 2) - EXCERPT_CHARS / 2);
  return { title, words: flat.split(" ").length, excerpt: flat.slice(middle, middle + EXCERPT_CHARS) };
}

// Fetch the shared page and pull out its title, the way the real app would resolve an episode or article
export async function probeUrl(url: string): Promise<ProbeResult> {
  const started = Date.now();

  // A hung request must read as a timeout, not as "the extension has no network"
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS);
  try {
    const response = await fetch(url, {
      headers: { "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)" },
      signal: controller.signal,
    });
    const html = await response.text();
    const title = html.match(/<title[^>]*>([^<]*)<\/title>/i)?.[1]?.trim();
    return { status: response.status, millis: Date.now() - started, title };
  } catch (error) {
    return { millis: Date.now() - started, error: String(error) };
  } finally {
    clearTimeout(timer);
  }
}

// The native side percent-encodes query values again, so swap "%" for "~" (which neither side touches) to keep
// the record intact; literal "~" is escaped first so the swap can be undone exactly
export function encodeRecord(record: SharedRecord): string {
  return encodeURIComponent(JSON.stringify(record)).replace(/~/g, "%7E").replace(/%/g, "~");
}

export function decodeRecord(encoded: string): SharedRecord {
  return JSON.parse(decodeURIComponent(encoded.replace(/~/g, "%")));
}

function safeHost(url: string): string | undefined {
  try {
    return new URL(url).host;
  } catch {
    return undefined;
  }
}
