import { useLiveQuery } from "drizzle-orm/expo-sqlite";

import { db } from "@/db/client";
import * as schema from "@/db/schema";
import type { LibrarySource } from "@/library/join";
import type { ReviewData } from "@/review/eligibility";

import { backTomorrow, dayDoneChips, todayTasks, type TodayTasks } from "./todayTasks";

export type TodayTaskView = { tasks: TodayTasks; backTomorrow: string; chips: string[] };

/** Today's task states, live, from the library and review rows the screen already reads plus briefs. */
export function useTodayTasks(sources: LibrarySource[], reviewData: ReviewData, now: Date): TodayTaskView {
  const { data: briefs } = useLiveQuery(db.select().from(schema.briefs));

  // The review log is already live in `reviewData`; a second query would re-read it on every grade.
  const inputs = { reviewData, reviews: reviewData.reviews, sources, briefs, now };
  const tasks = todayTasks(inputs);
  return { tasks, backTomorrow: backTomorrow(inputs, tasks), chips: dayDoneChips(tasks) };
}
