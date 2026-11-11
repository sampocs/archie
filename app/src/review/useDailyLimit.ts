import { useLiveQuery } from "drizzle-orm/expo-sqlite";
import { useState } from "react";

import { db } from "@/db/client";
import { getReviewSettings, reviewSettingsOf } from "@/db/reviewSettings";
import * as schema from "@/db/schema";

/**
 * Cards per day (null for no cap), live, so a change in Settings shows at once on Today and the Review tab.
 * Seeded from a synchronous read because the live query starts empty, which would flash the default cap.
 */
export function useDailyLimit(): number | null {
  const { data: rows } = useLiveQuery(db.select().from(schema.reviewSettings));
  const [initial] = useState(() => getReviewSettings(db).dailyLimit);
  return rows.length > 0 ? reviewSettingsOf(rows[0]).dailyLimit : initial;
}
