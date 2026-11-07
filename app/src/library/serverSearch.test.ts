import { createDebouncer, parseSearchResults, searchView } from "./serverSearch";

describe("parseSearchResults", () => {
  it("maps the server's rows and drops malformed ones", () => {
    const body = {
      results: [
        {
          item_kind: "source",
          item_id: "s1",
          title: "Odd Lots",
          passage: "…the Fed doesn't print money…",
          owner_kind: "source_text",
          start_seconds: 1880,
        },
        { item_kind: "mystery", item_id: "x" },
      ],
    };

    expect(parseSearchResults(body)).toEqual([
      {
        itemKind: "source",
        itemId: "s1",
        title: "Odd Lots",
        passage: "…the Fed doesn't print money…",
        ownerKind: "source_text",
        startSeconds: 1880,
      },
    ]);
    expect(parseSearchResults(null)).toEqual([]);
  });
});

describe("searchView", () => {
  const ready = { status: "ready" as const, results: [] };

  it("shows the server's results once they arrive while online", () => {
    expect(searchView({ query: "fed", online: true, state: ready })).toEqual({ mode: "server", offlineLine: false });
  });

  it("keeps on-phone matching while the request runs, without the offline line", () => {
    expect(searchView({ query: "fed", online: true, state: { status: "loading", results: [] } })).toEqual({
      mode: "local",
      offlineLine: false,
    });
  });

  it("falls back to on-phone matching with the offline line when offline or the request failed", () => {
    expect(searchView({ query: "fed", online: false, state: ready })).toEqual({ mode: "local", offlineLine: true });
    expect(searchView({ query: "fed", online: true, state: { status: "failed", results: [] } })).toEqual({
      mode: "local",
      offlineLine: true,
    });
  });
});

describe("createDebouncer", () => {
  it("runs only the last task, 300 ms after the last keystroke", () => {
    jest.useFakeTimers();
    const ran: string[] = [];
    const debouncer = createDebouncer(300);

    debouncer.run(() => ran.push("f"));
    jest.advanceTimersByTime(200);
    debouncer.run(() => ran.push("fe"));
    jest.advanceTimersByTime(299);
    expect(ran).toEqual([]);
    jest.advanceTimersByTime(1);
    expect(ran).toEqual(["fe"]);

    debouncer.run(() => ran.push("fed"));
    debouncer.cancel();
    jest.advanceTimersByTime(1000);
    expect(ran).toEqual(["fe"]);
    jest.useRealTimers();
  });
});
