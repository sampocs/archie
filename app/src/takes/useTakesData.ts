import { isNotNull, isNull } from "drizzle-orm";
import { useLiveQuery } from "drizzle-orm/expo-sqlite";
import { useMemo } from "react";

import { db } from "@/db/client";
import * as schema from "@/db/schema";

import { groupTakes, type TakeWithVersions } from "./takes";

/**
 * Every live take with its versions and card count, plus whether the live queries have answered: drizzle's
 * `useLiveQuery` returns `[]` on first render, so "no take" only means "gone" once `loaded`.
 */
export function useTakesState(): { takes: TakeWithVersions[]; loaded: boolean } {
  const { data: takes, updatedAt: takesUpdatedAt } = useLiveQuery(
    db.select().from(schema.takes).where(isNull(schema.takes.deletedAt)),
  );
  const { data: versions, updatedAt: versionsUpdatedAt } = useLiveQuery(db.select().from(schema.takeVersions));
  const { data: cards } = useLiveQuery(db.select().from(schema.cards).where(isNotNull(schema.cards.takeId)));

  const grouped = useMemo(() => groupTakes(takes, versions, cards), [takes, versions, cards]);
  return { takes: grouped, loaded: takesUpdatedAt !== undefined && versionsUpdatedAt !== undefined };
}

/** Every live take, for the Takes list, the take page and the editor. */
export function useTakesData(): TakeWithVersions[] {
  return useTakesState().takes;
}
