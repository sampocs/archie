import { showsOrigin, versionKicker } from "./versionView";

describe("showsOrigin", () => {
  it("shows over text that was cleaned", () => {
    expect(showsOrigin("cleaned", { body: "- Point", rawBody: "so basically point" })).toBe(true);
  });

  it("hides when the body is just the raw text (a restored, never-cleaned version)", () => {
    expect(showsOrigin("cleaned", { body: "same", rawBody: "same" })).toBe(false);
  });

  it("hides in every other state", () => {
    expect(showsOrigin("none", { body: "a", rawBody: "b" })).toBe(false);
    expect(showsOrigin("failed", { body: "a", rawBody: "b" })).toBe(false);
    expect(showsOrigin("cleaning", { body: null, rawBody: "b" })).toBe(false);
  });
});

describe("versionKicker", () => {
  it("adds how the version was made when it wasn't the owner's own save", () => {
    const now = new Date(2026, 10, 5);
    const createdAt = new Date(2026, 10, 2).toISOString();
    expect(versionKicker({ version: 3, createdAt, origin: "chat_edit" }, now)).toBe("Version 3 · Nov 2 · Edited in Ask");
    expect(versionKicker({ version: 3, createdAt, origin: "owner" }, now)).toBe("Version 3 · Nov 2");
  });

  it("names the version and its date", () => {
    const now = new Date(2026, 10, 5);
    expect(versionKicker({ version: 2, createdAt: new Date(2026, 10, 2).toISOString() }, now)).toBe("Version 2 · Nov 2");
  });
});
