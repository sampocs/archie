import { isNull } from "drizzle-orm";

import { addCollectionItem, addSource, createCollection } from "@/db/actions";
import * as schema from "@/db/schema";
import { makeTestDb } from "@/db/testDb";
import { joinLibrary } from "@/library/join";
import { matchesQuery, searchText } from "@/library/search";

jest.mock("expo-crypto", () => ({ randomUUID: () => require("crypto").randomUUID() }));

// Collection posts live in their own table, so the Library's queries (the same ones `useLibraryData` runs) and its
// search can't see them: All, Domains, Today and search read only `sources`.
it("a saved post never reaches the library's sources or its search", async () => {
  const db = makeTestDb();
  await addSource(db, { url: "https://example.com/reading", intent: "queue" });
  const collectionId = createCollection(db, "Bears hype");
  addCollectionItem(db, { collectionId, url: "https://x.com/BearsFilmRoom/status/1" });

  const sources = db.select().from(schema.sources).where(isNull(schema.sources.deletedAt)).all();
  const library = joinLibrary({ sources, artifacts: [], topics: [], topicPrimers: [], cardCounts: new Map() });

  expect(library.sources.map((source) => source.url)).toEqual(["https://example.com/reading"]);
  expect(library.sources.filter((source) => matchesQuery(searchText(source), "bears"))).toEqual([]);
});
