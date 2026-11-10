import { detailLines } from "./detail";

describe("detailLines", () => {
  it("splits on newlines, trims each line and drops blanks", () => {
    expect(detailLines("  First \n\n Second\n   \nThird")).toEqual(["First", "Second", "Third"]);
  });

  it("gives no lines for no detail", () => {
    expect(detailLines("")).toEqual([]);
  });
});
