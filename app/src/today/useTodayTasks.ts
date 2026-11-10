import { gte } from "drizzle-orm";
import { useLiveQuery } from "drizzle-orm/expo-sqlite";
import { useMemo } from "react";

import { db } from "@/db/client";
import * as schema from "@/db/schema";
import type { LibrarySource } from "@/library/join";
import type { ReviewData } from "@/review/eligibility";

import { localDate } from "./todayLabels";
import { backTomorrow, dayDoneChips, todayTasks, type TodayTasks } from "./todayTasks";

// A week of the review log covers an open quiz's answers (a quiz runs Sunday to Saturday) as well as today's reviews.
const REVIEW_LOG_DAYS = 7;

export type TodayTaskView = { tasks: TodayTasks; backTomorrow: string; chips: string[] };

/** Today's task states, live, from the library and review rows the screen already reads plus briefs and reviews. */
export function useTodayTasks(sources: LibrarySource[], reviewData: ReviewData, now: Date): TodayTaskView {
  const day = localDate(now);
  // Recomputed only when the local day turns, not on every tick of `now`.
  const since = useMemo(
    () => new Date(now.getFullYear(), now.getMonth(), now.getDate() - REVIEW_LOG_DAYS).toISOString(),
    [day],
  );
  const { data: briefs } = useLiveQuery(db.select().from(schema.briefs));
  const { data: reviews } = useLiveQuery(
    db.select().from(schema.reviews).where(gte(schema.reviews.reviewedAt, since)),
    [since],
  );

  const inputs = { reviewData, reviews, sources, briefs, now };
  const tasks = todayTasks(inputs);
  return { tasks, backTomorrow: backTomorrow(inputs, tasks), chips: dayDoneChips(tasks) };
}
