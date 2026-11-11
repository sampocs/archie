import { ClientError, NetworkError } from "@/api/client";

import {
  bookMatchLine,
  goodreadsSlugTitle,
  isBookQuery,
  isGoodreadsBookUrl,
  LOOKUP_NOT_FOUND_MESSAGE,
  LOOKUP_OFFLINE_MESSAGE,
  lookupErrorMessage,
  parseBookMatch,
  sharedBookFallback,
} from "./books";

describe("isBookQuery", () => {
  it.each([
    ["the spy and the traitor", true],
    ["  Thinking, Fast and Slow  ", true],
    // No scheme, so not an http(s) link: the + sheet looks it up as a title.
    ["example.com/article", true],
    ["mailto:a@b.co", true],
    ["https://example.com/a", false],
    ["  http://example.com  ", false],
    ["", false],
    ["   ", false],
  ])("%p → %p", (text, expected) => {
    expect(isBookQuery(text)).toBe(expected);
  });
});

describe("isGoodreadsBookUrl", () => {
  it.each([
    ["https://www.goodreads.com/book/show/41817486-the-spy-and-the-traitor", true],
    ["https://goodreads.com/book/show/11468377", true],
    ["http://m.goodreads.com/book/show/1.Title?ref=share", true],
    ["https://www.goodreads.com/author/show/1234.Ben_Macintyre", false],
    ["https://www.goodreads.com/book/show/", false],
    ["https://notgoodreads.com/book/show/1-x", false],
    ["https://example.com/?u=https://www.goodreads.com/book/show/1-x", false],
  ])("%p → %p", (url, expected) => {
    expect(isGoodreadsBookUrl(url)).toBe(expected);
  });
});

describe("goodreadsSlugTitle", () => {
  it("reads the title from either slug style, and null for an id alone or another link", () => {
    expect(goodreadsSlugTitle("https://www.goodreads.com/book/show/41817486-the-spy-and-the-traitor")).toBe(
      "the spy and the traitor",
    );
    expect(goodreadsSlugTitle("https://www.goodreads.com/book/show/11468377.Thinking_Fast_and_Slow?ac=1")).toBe(
      "Thinking Fast and Slow",
    );
    expect(goodreadsSlugTitle("https://www.goodreads.com/book/show/11468377")).toBeNull();
    expect(goodreadsSlugTitle("https://example.com/book/show/1-x")).toBeNull();
  });
});

describe("sharedBookFallback", () => {
  const url = "https://www.goodreads.com/book/show/41817486-the-spy-and-the-traitor";

  it("prefers the shared title, then the link's slug, then the link, with no author or cover", () => {
    expect(sharedBookFallback(url, "The Spy and the Traitor")).toEqual({
      title: "The Spy and the Traitor",
      author: null,
      year: null,
      coverUrl: null,
      url,
    });
    expect(sharedBookFallback(url, "  ").title).toBe("the spy and the traitor");
    expect(sharedBookFallback("https://goodreads.com/book/show/41817486", null).title).toBe(
      "https://goodreads.com/book/show/41817486",
    );
  });
});

describe("parseBookMatch", () => {
  it("reads the wire fields, leaving unknown ones null", () => {
    expect(
      parseBookMatch({
        title: "Thinking, Fast and Slow",
        author: "Daniel Kahneman",
        year: 2011,
        cover_url: "https://covers.openlibrary.org/b/id/1-L.jpg",
        url: "https://openlibrary.org/works/OL1W",
      }),
    ).toEqual({
      title: "Thinking, Fast and Slow",
      author: "Daniel Kahneman",
      year: 2011,
      coverUrl: "https://covers.openlibrary.org/b/id/1-L.jpg",
      url: "https://openlibrary.org/works/OL1W",
    });
    expect(parseBookMatch({ title: "T", url: "https://x.test", author: null, year: null, cover_url: null })).toEqual({
      title: "T",
      url: "https://x.test",
      author: null,
      year: null,
      coverUrl: null,
    });
  });

  it("is null without a title or url", () => {
    expect(parseBookMatch({ url: "https://x.test" })).toBeNull();
    expect(parseBookMatch({ title: "T" })).toBeNull();
    expect(parseBookMatch(null)).toBeNull();
  });
});

describe("bookMatchLine", () => {
  it.each([
    [{ author: "Ben Macintyre", year: 2018 }, "Ben Macintyre · 2018"],
    [{ author: "Ben Macintyre", year: null }, "Ben Macintyre"],
    [{ author: null, year: 2018 }, "2018"],
    [{ author: null, year: null }, null],
  ])("%p → %p", (match, expected) => {
    expect(bookMatchLine(match)).toBe(expected);
  });
});

describe("lookupErrorMessage", () => {
  it("says no book for a 404 and couldn't look it up for anything else", () => {
    expect(lookupErrorMessage(new ClientError("404 from /books/lookup", 404))).toBe(LOOKUP_NOT_FOUND_MESSAGE);
    expect(lookupErrorMessage(new ClientError("422 from /books/lookup", 422))).toBe(LOOKUP_OFFLINE_MESSAGE);
    expect(lookupErrorMessage(new NetworkError("502 from /books/lookup"))).toBe(LOOKUP_OFFLINE_MESSAGE);
  });
});
