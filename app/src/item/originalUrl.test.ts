import { originalUrl } from "./originalUrl";

describe("originalUrl", () => {
  it("is the address of a web page", () => {
    expect(originalUrl("https://github.com/example/repo")).toBe("https://github.com/example/repo");
    expect(originalUrl("HTTP://example.com/post")).toBe("HTTP://example.com/post");
  });

  it("is null for an item's placeholder address", () => {
    for (const url of ["note:abc", "book:123", "chat:xyz", "newsletter:<id@example.com>"]) {
      expect(originalUrl(url)).toBeNull();
    }
  });
});
