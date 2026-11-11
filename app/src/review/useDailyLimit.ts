import { useLiveQuery } from "drizzle-orm/expo-sqlite";

import { db } from "@/db/client";
import { reviewSettingsOf } from "@/db/reviewSettings";
import * as schema from "@/db/schema";

/** Cards per day (null for no cap), live, so a change in Settings shows at once on Today and the Review tab. */
export function useDailyLimit(): number | null {
  const { data: rows } = useLiveQuery(db.select().from(schema.reviewSettings));
  return reviewSettingsOf(rows[0]).dailyLimit;
}
