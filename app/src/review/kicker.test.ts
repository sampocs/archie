import { cardKicker } from "./kicker";
import { cardRow, reviewData, takeRow } from "./testCards";

describe("cardKicker", () => {
  const data = reviewData([], { takes: [takeRow({ id: "k1", kind: "opinion" }), takeRow({ id: "k2" })] });
  const takeCard = (takeId: string) => cardRow({ sourceId: null, takeId, kind: "take" });

  it("reads This week · News for a quiz card", () => {
    expect(cardKicker(cardRow({ sourceId: null, briefId: "b1", kind: "quiz" }), data)).toEqual({
      label: "This week",
      suffix: "News",
      domain: null,
    });
  });

  it("reads Your take · <kind> in the kind's colour for a take card", () => {
    expect(cardKicker(takeCard("k1"), data)).toEqual({ label: "Your take", suffix: "Opinion", domain: "History" });
    expect(cardKicker(takeCard("k2"), data)).toEqual({ label: "Your take", suffix: "Talking point", domain: "Startups" });
    expect(cardKicker(takeCard("gone"), data)).toEqual({
      label: "Your take",
      suffix: "Talking point",
      domain: "Startups",
    });
  });

  it("reads the kind in the source's domain colour for a source card", () => {
    expect(cardKicker(cardRow({}), data)).toEqual({ label: undefined, suffix: "Concept", domain: "AI" });
  });
});
