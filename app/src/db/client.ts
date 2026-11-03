import { drizzle } from "drizzle-orm/expo-sqlite";
import { useMigrations } from "drizzle-orm/expo-sqlite/migrator";
import { BaseSQLiteDatabase } from "drizzle-orm/sqlite-core";
import { openDatabaseSync } from "expo-sqlite";

import migrations from "../../drizzle/migrations";
import * as schema from "./schema";

// Both expo-sqlite (app) and better-sqlite3 (tests) are synchronous drivers, so they share this type.
export type AppDb = BaseSQLiteDatabase<"sync", unknown, typeof schema>;

export const db = drizzle(openDatabaseSync("archie.db", { enableChangeListener: true }), { schema });

export function useDbMigrations() {
  return useMigrations(db, migrations);
}

// Single-row sync bookkeeping table; idempotent so it can run on every launch.
export function seedSyncState(): void {
  db.insert(schema.syncState)
    .values({ id: 1, position: 0, lastPushFailed: 0 })
    .onConflictDoNothing()
    .run();
}
