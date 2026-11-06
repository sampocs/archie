import { canSaveToCollection, collectionPickLabel, defaultCollectionPick } from "./collectionChoice";
import { chooseIntent, EMPTY_CHOICE } from "./types";

const collections = [
  { id: "a", name: "Film study" },
  { id: "b", name: "Recipes" },
];

describe("defaultCollectionPick", () => {
  it("prefers the last-used collection, else the newest, else a new one", () => {
    expect(defaultCollectionPick(collections, "a")).toEqual({ kind: "existing", id: "a" });
    expect(defaultCollectionPick(collections, "gone")).toEqual({ kind: "existing", id: "b" });
    expect(defaultCollectionPick([], null)).toEqual({ kind: "new", name: "" });
  });
});

describe("collectionPickLabel", () => {
  it("names the collection, the typed name, or New collection…", () => {
    expect(collectionPickLabel({ kind: "existing", id: "a" }, collections)).toBe("Film study");
    expect(collectionPickLabel({ kind: "new", name: "  " }, collections)).toBe("New collection…");
    expect(collectionPickLabel({ kind: "new", name: "Trips" }, collections)).toBe("Trips");
    expect(collectionPickLabel({ kind: "existing", id: "gone" }, collections)).toBe("New collection…");
  });
});

describe("canSaveToCollection", () => {
  it("needs a pick, and a name for a new collection where nothing can ask for one", () => {
    expect(canSaveToCollection(null, { asksForName: true })).toBe(false);
    expect(canSaveToCollection({ kind: "existing", id: "a" }, { asksForName: false })).toBe(true);
    expect(canSaveToCollection({ kind: "new", name: " " }, { asksForName: true })).toBe(true);
    expect(canSaveToCollection({ kind: "new", name: " " }, { asksForName: false })).toBe(false);
    expect(canSaveToCollection({ kind: "new", name: "Trips" }, { asksForName: false })).toBe(true);
  });
});

describe("chooseIntent with collections", () => {
  const pick = { kind: "existing" as const, id: "a" };

  it("seeds the pick and clears the library answers", () => {
    const finished = { ...EMPTY_CHOICE, intent: "finished" as const, reaction: "easy" as const, note: "x" };

    expect(chooseIntent(finished, "collection", pick)).toEqual({ ...EMPTY_CHOICE, intent: "collection", collection: pick });
  });

  it("starts with no pick when none is given, and drops the pick when switching to queue", () => {
    expect(chooseIntent(EMPTY_CHOICE, "collection").collection).toBeNull();
    const inCollection = chooseIntent(EMPTY_CHOICE, "collection", pick);

    expect(chooseIntent(inCollection, "queue")).toEqual({ ...EMPTY_CHOICE, intent: "queue" });
  });
});
