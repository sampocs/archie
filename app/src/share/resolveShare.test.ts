import { resolveShare } from "./resolveShare";

describe("resolveShare", () => {
  it("prefers the url prop, then a url inside the text, then the page's own url", () => {
    const preprocessingResults = { url: "https://page.com/p", title: "P", text: "body" };

    expect(resolveShare({ url: "https://prop.com", text: "see https://text.com", preprocessingResults }).url).toBe("https://prop.com");
    expect(resolveShare({ text: "see https://text.com", preprocessingResults }).url).toBe("https://text.com");
    expect(resolveShare({ preprocessingResults }).url).toBe("https://page.com/p");
  });

  it("has no url when nothing carries one", () => {
    expect(resolveShare({ text: "just words" })).toEqual({ url: null, capture: null, title: null });
  });

  it("takes the capture's title, else the host, and ignores an empty capture", () => {
    const withTitle = resolveShare({ url: "https://a.com/x", preprocessingResults: { title: "Hello", text: "body" } });
    const empty = resolveShare({ url: "https://a.com/x", preprocessingResults: { title: "Hello", text: "  " } });

    expect(withTitle).toMatchObject({ title: "Hello", capture: { title: "Hello", text: "body" } });
    expect(empty).toEqual({ url: "https://a.com/x", capture: null, title: "a.com" });
  });
});
