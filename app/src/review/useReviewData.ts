import { eq, isNull } from "drizzle-orm";
import { useLiveQuery } from "drizzle-orm/expo-sqlite";
import { useMemo } from "react";

import { type AppDb, db } from "@/db/client";
import * as schema from "@/db/schema";

import { makeReviewData, type ReviewData } from "./eligibility";

/** The rows review logic reads: non-deleted cards, sources and takes, current topic primers, and every topic. */
export function reviewQueries(database: AppDb) {
  return {
    cards: database.select().from(schema.cards).where(isNull(schema.cards.deletedAt)),
    sources: database.select().from(schema.sources).where(isNull(schema.sources.deletedAt)),
    topicPrimers: database.select().from(schema.topicPrimers).where(eq(schema.topicPrimers.isCurrent, 1)),
    topics: database.select().from(schema.topics),
    takes: database.select().from(schema.takes).where(isNull(schema.takes.deletedAt)),
  };
}

/** The same rows, read once (a session's card list, the reminder plan). */
export function readReviewData(database: AppDb): ReviewData {
  const queries = reviewQueries(database);
  return makeReviewData({
    cards: queries.cards.all(),
    sources: queries.sources.all(),
    topicPrimers: queries.topicPrimers.all(),
    topics: queries.topics.all(),
    takes: queries.takes.all(),
  });
}

/** Everything the review screens read, live. */
export function useReviewData(): ReviewData {
  const queries = useMemo(() => reviewQueries(db), []);
  const { data: cards } = useLiveQuery(queries.cards);
  const { data: sources } = useLiveQuery(queries.sources);
  const { data: topicPrimers } = useLiveQuery(queries.topicPrimers);
  const { data: topics } = useLiveQuery(queries.topics);
  const { data: takes } = useLiveQuery(queries.takes);

  return useMemo(
    () => makeReviewData({ cards, sources, topicPrimers, topics, takes }),
    [cards, sources, topicPrimers, topics, takes],
  );
}
