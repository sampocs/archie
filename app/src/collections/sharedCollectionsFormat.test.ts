import { encodeSharedCollections, parseSharedCollections } from "./sharedCollectionsFormat";

describe("shared collections format", () => {
  it("round-trips the list, keeping only id and name", () => {
    const list = [
      { id: "a", name: "Bears hype" },
      { id: "b", name: "Funny" },
    ];

    expect(parseSharedCollections(encodeSharedCollections(list))).toEqual(list);
  });

  it.each([null, "", "not json", "{}", '[{"id": 1}]'])("reads %p as no collections", (raw) => {
    expect(parseSharedCollections(raw)).toEqual([]);
  });

  it("keeps the good entries of a list with a malformed one", () => {
    const raw = JSON.stringify([{ id: "a", name: "Bears hype" }, { id: "b" }, null, { id: "c", name: "Funny" }]);

    expect(parseSharedCollections(raw)).toEqual([
      { id: "a", name: "Bears hype" },
      { id: "c", name: "Funny" },
    ]);
  });
});
