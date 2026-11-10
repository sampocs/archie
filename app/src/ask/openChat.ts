import { randomUUID } from "expo-crypto";
import type { useRouter } from "expo-router";

import type { AboutKind } from "./types";

/**
 * A new chat about one item (Ask about this): its passages rank first and the composer shows "About: <title>". A
 * `question` is sent as soon as the chat opens. `fromNote` is set when the chat opens from that note's page, so
 * the chat's Open goes back to the page instead of stacking a second one.
 */
export function openChat(
  router: ReturnType<typeof useRouter>,
  about: { kind: AboutKind; id: string; title: string },
  question?: string,
  fromNote?: boolean,
): void {
  router.push({
    pathname: "/ask/[id]",
    params: {
      id: randomUUID(),
      aboutKind: about.kind,
      aboutId: about.id,
      aboutTitle: about.title,
      ...(fromNote ? { fromNote: about.id } : {}),
      ...(question ? { q: question, web: "0" } : {}),
    },
  });
}
