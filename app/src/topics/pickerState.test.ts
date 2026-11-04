import type { ChosenTopic } from "@/db/actions";

import { addOwn, togglePick } from "./pickerState";

const inflation: ChosenTopic = { domain: "Macro", name: "Inflation", origin: "starter" };

describe("togglePick", () => {
  it("adds a topic, then removes it on the second tap", () => {
    const once = togglePick([], inflation);
    expect(once).toEqual([inflation]);
    expect(togglePick(once, inflation)).toEqual([]);
  });
});

describe("addOwn", () => {
  it("adds a user topic with the whitespace collapsed", () => {
    const result = addOwn([], "AI", "  Robotics   labs ");
    expect(result.error).toBeNull();
    expect(result.picked).toEqual([{ domain: "AI", name: "Robotics labs", origin: "user" }]);
  });

  it("rejects empty and too-long names", () => {
    expect(addOwn([], "AI", "   ").error).not.toBeNull();
    expect(addOwn([], "AI", "x".repeat(81)).error).not.toBeNull();
  });

  it("rejects a name that normalizes like a picked one", () => {
    const result = addOwn([inflation], "Macro", "inflation");
    expect(result.error).toBe("Already picked.");
    expect(result.picked).toEqual([inflation]);
  });
});
