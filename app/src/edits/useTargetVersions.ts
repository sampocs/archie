import { and, eq } from "drizzle-orm";
import { useLiveQuery } from "drizzle-orm/expo-sqlite";
import { useMemo } from "react";

import { db } from "@/db/client";
import * as schema from "@/db/schema";

import type { EditTargetKind } from "./types";
import { artifactEntries, cardEntries, takeEntries, topicPrimerEntries, type VersionEntry } from "./versions";

// A key no row has, so a query for another kind of target reads nothing.
const NONE = "";

/** A target's versions, newest first, and its current version number (null until loaded, or when it is gone). */
export function useTargetVersions(
  kind: EditTargetKind | null,
  id: string | null,
): { current: number | null; entries: VersionEntry[] } {
  const artifactKind = kind === "summary" || kind === "primer" ? kind : null;
  const key = (wanted: boolean) => (wanted && id ? id : NONE);

  const { data: artifacts } = useLiveQuery(
    db
      .select()
      .from(schema.artifacts)
      .where(and(eq(schema.artifacts.sourceId, key(artifactKind !== null)), eq(schema.artifacts.kind, artifactKind ?? NONE))),
    [id, artifactKind],
  );
  const { data: primers } = useLiveQuery(
    db.select().from(schema.topicPrimers).where(eq(schema.topicPrimers.topicId, key(kind === "topic_primer"))),
    [id, kind],
  );
  const { data: takes } = useLiveQuery(
    db.select().from(schema.takes).where(eq(schema.takes.id, key(kind === "take"))),
    [id, kind],
  );
  const { data: takeVersions } = useLiveQuery(
    db.select().from(schema.takeVersions).where(eq(schema.takeVersions.takeId, key(kind === "take"))),
    [id, kind],
  );
  const { data: cards } = useLiveQuery(
    db.select().from(schema.cards).where(eq(schema.cards.id, key(kind === "card"))),
    [id, kind],
  );
  const { data: cardVersions } = useLiveQuery(
    db.select().from(schema.cardVersions).where(eq(schema.cardVersions.cardId, key(kind === "card"))),
    [id, kind],
  );

  return useMemo(() => {
    const entries = entriesFor({ kind, artifactKind, artifacts, primers, takes, takeVersions, cards, cardVersions });
    return { current: entries.find((entry) => entry.current)?.version ?? null, entries };
  }, [kind, artifactKind, artifacts, primers, takes, takeVersions, cards, cardVersions]);
}

function entriesFor(input: {
  kind: EditTargetKind | null;
  artifactKind: "summary" | "primer" | null;
  artifacts: (typeof schema.artifacts.$inferSelect)[];
  primers: (typeof schema.topicPrimers.$inferSelect)[];
  takes: (typeof schema.takes.$inferSelect)[];
  takeVersions: (typeof schema.takeVersions.$inferSelect)[];
  cards: (typeof schema.cards.$inferSelect)[];
  cardVersions: (typeof schema.cardVersions.$inferSelect)[];
}): VersionEntry[] {
  if (input.artifactKind) return artifactEntries(input.artifactKind, input.artifacts);
  if (input.kind === "topic_primer") return topicPrimerEntries(input.primers);
  if (input.kind === "take") {
    const take = input.takes[0];
    return take && take.deletedAt === null ? takeEntries(take, input.takeVersions) : [];
  }
  if (input.kind === "card") {
    const card = input.cards[0];
    return card && card.deletedAt === null ? cardEntries(card, input.cardVersions) : [];
  }
  return [];
}
