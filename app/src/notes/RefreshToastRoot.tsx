import { and, count, eq, isNull } from "drizzle-orm";
import { useLiveQuery } from "drizzle-orm/expo-sqlite";

import { db } from "@/db/client";
import * as schema from "@/db/schema";
import { Toast } from "@/ui/Toast";

import { clearPendingRefreshToast, usePendingRefreshToast } from "./pendingToast";
import { cardsAddedMessage } from "./refresher";

/** Announces "N review cards added from …" once a refreshed note's cards arrive, on whatever screen the user is on. */
export function RefreshToastRoot() {
  const pending = usePendingRefreshToast();
  const { data } = useLiveQuery(
    db
      .select({ count: count() })
      .from(schema.cards)
      .where(and(eq(schema.cards.sourceId, pending?.sourceId ?? ""), isNull(schema.cards.deletedAt))),
    [pending?.sourceId],
  );
  const cardCount = data[0]?.count ?? 0;

  // The cards are made by the server after Done syncs, so nothing shows until they land.
  if (!pending || cardCount === 0) return null;

  return <Toast message={cardsAddedMessage(cardCount, pending.title)} onHide={clearPendingRefreshToast} />;
}
