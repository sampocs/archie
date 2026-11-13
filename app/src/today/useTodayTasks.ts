import { useLiveQuery } from "drizzle-orm/expo-sqlite";

import { db } from "@/db/client";
import * as schema from "@/db/schema";
import type { LibrarySource } from "@/library/join";
import type { ReviewData } from "@/review/eligibility";

import { backTomorrow, dayDoneChips, todayTasks, tomorrowCounts, type TodayTasks, type TomorrowCounts } from "./todayTasks";

export type TodayTaskView = { tasks: TodayTasks; tomorrow: TomorrowCounts; backTomorrow: string; chips: string[] };

/** Today's task states, live, from the library and review rows the screen already reads plus briefs. */
export function useTodayTasks(
  sources: LibrarySource[],
  reviewData: ReviewData,
  dailyLimit: number | null,
  now: Date,
): TodayTaskView {
  const { data: briefs } = useLiveQuery(db.select().from(schema.briefs));

  // The review log is already live in `reviewData`; a second query would re-read it on every grade.
  const inputs = { reviewData, reviews: reviewData.reviews, sources, briefs, dailyLimit, now };
  const tasks = todayTasks(inputs);
  const tomorrow = tomorrowCounts(inputs, tasks);
  return { tasks, tomorrow, backTomorrow: backTomorrow(tomorrow), chips: dayDoneChips(tasks) };
}
