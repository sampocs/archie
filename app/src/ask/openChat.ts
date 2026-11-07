import { randomUUID } from "expo-crypto";
import type { Router } from "expo-router";

import type { AboutKind } from "./types";

/** A new chat about one item (Ask about this): its passages rank first and the composer shows "About: <title>". */
export function openChat(router: Router, about: { kind: AboutKind; id: string; title: string }): void {
  router.push({
    pathname: "/ask/[id]",
    params: { id: randomUUID(), aboutKind: about.kind, aboutId: about.id, aboutTitle: about.title },
  });
}
