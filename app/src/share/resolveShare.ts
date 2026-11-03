import type { InitialProps } from "expo-share-extension";

import { extractFirstUrl } from "@/capture/extractUrl";

export type ResolvedShare = {
  url: string | null;
  // The page as the logged-in user sees it: only Safari shares carry it (preprocessing.js).
  capture: { title: string | null; text: string } | null;
  title: string | null;
};

type PreprocessingResults = { url?: string; title?: string; text?: string };

export function resolveShare(props: InitialProps): ResolvedShare {
  const preprocessed = (props.preprocessingResults ?? {}) as PreprocessingResults;

  // Spotify and YouTube send only text with the link inside it; Safari pages with a paywall send no `url` prop.
  const url = props.url ?? extractFirstUrl(props.text ?? "") ?? preprocessed.url ?? null;
  const capture = preprocessed.text?.trim() ? { title: preprocessed.title || null, text: preprocessed.text } : null;

  return { url, capture, title: capture?.title ?? hostOf(url) };
}

// A regex, not `new URL`: React Native's URL polyfill is incomplete, and the sheet must not crash on odd input.
function hostOf(url: string | null): string | null {
  return url?.match(/^https?:\/\/([^/?#]+)/i)?.[1] ?? null;
}
