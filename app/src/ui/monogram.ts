import { CHAT_KIND } from "./sourceLabels";

/** The glyph on the artwork tile of a primer row. */
export const PRIMER_MONOGRAM = "◆";

type MonogramItem = { kind: string; title: string | null; sender: string | null; url: string };

function firstLetterOrDigit(text: string | null): string | null {
  const match = text?.match(/[\p{L}\p{N}]/u);
  return match ? match[0].toUpperCase() : null;
}

function hostname(url: string): string | null {
  return URL.canParse(url) ? new URL(url).hostname.replace(/^www\./, "") : null;
}

/** The letter shown when a source has no artwork: sender, else title, else site; a glyph for YouTube, notes and chats. */
export function monogramFor(item: MonogramItem): string {
  if (item.kind === "youtube") return "▶";
  if (item.kind === "note") return "✎";
  if (item.kind === CHAT_KIND) return "✦";
  return (
    firstLetterOrDigit(item.sender) ?? firstLetterOrDigit(item.title) ?? firstLetterOrDigit(hostname(item.url)) ?? "?"
  );
}
