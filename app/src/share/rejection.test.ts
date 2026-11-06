import { isUnpushedCollectionRejection } from "./rejection";

describe("isUnpushedCollectionRejection", () => {
  it("treats a collection the server does not know as recoverable", () => {
    expect(isUnpushedCollectionRejection("collection not found")).toBe(true);
  });

  it("keeps other rejections as rejections", () => {
    expect(isUnpushedCollectionRejection("collection name is empty")).toBe(false);
  });
});
