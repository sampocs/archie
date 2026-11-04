import type { TopicRow } from "@/library/join";

import { normalizeTopicName, slugify, topicNameError } from "./topicName";

const topic = (overrides: Partial<TopicRow>): TopicRow => ({
  id: "t1",
  domain: "Macro",
  name: "Fed & monetary policy",
  origin: "starter",
  removedAt: null,
  mergedIntoId: null,
  createdAt: "2026-11-01T00:00:00Z",
  updatedAt: "2026-11-01T00:00:00Z",
  primerRequestedAt: null,
  ...overrides,
});

describe("normalizeTopicName", () => {
  it.each([
    ["Fed & Monetary Policy", "fed and monetary policy"],
    ["US–China", "us china"],
    ["AI/ML engineering", "ai ml engineering"],
    ["  Rollups & L2s!", "rollups and l2s"],
  ])("normalizes %p like the server does", (name, expected) => {
    expect(normalizeTopicName(name)).toBe(expected);
  });
});

describe("slugify", () => {
  it("makes a testID-safe name", () => {
    expect(slugify("Fed & monetary policy")).toBe("fed-monetary-policy");
  });
});

describe("topicNameError", () => {
  it("refuses an empty name", () => {
    expect(topicNameError("   ", [])).toBe("Give the topic a name.");
  });

  it("refuses a name over 80 characters", () => {
    expect(topicNameError("x".repeat(81), [])).toBe("Keep it under 80 characters.");
  });

  it("refuses a name that matches a live topic once normalized", () => {
    expect(topicNameError("fed and monetary  policy", [topic({})])).toBe("You already have this topic.");
  });

  it("points at Settings when the clash is a removed topic", () => {
    expect(topicNameError("Fed & monetary policy", [topic({ removedAt: "2026-11-02T00:00:00Z" })])).toBe(
      "You removed a topic with this name. Restore it in Settings.",
    );
  });

  it("accepts a rename to the topic's own name", () => {
    expect(topicNameError("Fed & Monetary Policy", [topic({})], "t1")).toBeNull();
  });

  it("ignores a merged topic's name", () => {
    expect(topicNameError("Fed & monetary policy", [topic({ mergedIntoId: "t2" })])).toBeNull();
  });
});
