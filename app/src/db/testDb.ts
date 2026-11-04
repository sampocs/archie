import Database from "better-sqlite3";
import { drizzle } from "drizzle-orm/better-sqlite3";

import migrations from "../../drizzle/migrations";
import type { AppDb } from "./client";
import * as schema from "./schema";

// Tests run against the app's real schema: every generated migration, in journal order.
export function makeTestDb(): AppDb {
  const sqlite = new Database(":memory:");
  const sqlByKey = migrations.migrations as Record<string, string>;
  for (const entry of migrations.journal.entries) {
    const sql = sqlByKey[`m${String(entry.idx).padStart(4, "0")}`];
    for (const statement of sql.split("--> statement-breakpoint")) {
      if (statement.trim()) sqlite.exec(statement);
    }
  }
  sqlite.prepare("INSERT INTO sync_state (id, position, last_push_failed) VALUES (1, 0, 0)").run();
  return drizzle(sqlite, { schema }) as unknown as AppDb;
}
