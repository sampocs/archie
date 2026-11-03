import { EMPTY_CHOICE } from "@/capture/types";

import { buildShareAction, decodeShareParam, encodeShareParam, shareDeepLink, submitShare } from "./submit";

jest.mock("expo-crypto", () => {
  let counter = 0;
  return { randomUUID: () => `uuid-${++counter}` };
});

const finished = { intent: "finished" as const, reaction: "easy" as const, note: "clear", prepMe: false };
const queued = { ...EMPTY_CHOICE, intent: "queue" as const, prepMe: true };

describe("buildShareAction", () => {
  it("builds a snake_case add_source with fresh action and source ids and the capture", () => {
    const action = buildShareAction({
      url: "https://a.com/x",
      choice: finished,
      capture: { title: "T", text: "body" },
    });

    expect(action.type).toBe("add_source");
    expect(action.id).not.toBe((action.payload as { id: string }).id);
    expect(action.payload).toMatchObject({
      url: "https://a.com/x",
      intent: "finished",
      reaction: "easy",
      note: "clear",
      capture: { title: "T", text: "body" },
    });
  });

  it("omits unset options and sends prep_me only when on", () => {
    const { payload } = buildShareAction({ url: "https://a.com", choice: queued, capture: null });

    expect(payload).toEqual({ id: expect.any(String), url: "https://a.com", intent: "queue", prep_me: true });
  });

  it("drops a capture over 400,000 characters but keeps one exactly at the limit", () => {
    const over = buildShareAction({ url: "u", choice: queued, capture: { title: "T", text: "x".repeat(400_001) } });
    const exact = buildShareAction({ url: "u", choice: queued, capture: { title: "T", text: "x".repeat(400_000) } });

    expect(over.payload).not.toHaveProperty("capture");
    expect(exact.payload).toHaveProperty("capture");
  });

  it("truncates a title over 500 characters rather than losing the share to validation", () => {
    const { payload } = buildShareAction({ url: "u", choice: queued, capture: { title: "t".repeat(900), text: "x" } });

    expect((payload as { capture: { title: string } }).capture.title).toHaveLength(500);
  });

  it("truncates by code point so an emoji at the boundary is not split", () => {
    const title = "t".repeat(499) + "😀😀";
    const { payload } = buildShareAction({ url: "u", choice: queued, capture: { title, text: "x" } });

    expect((payload as { capture: { title: string } }).capture.title).toBe(Array.from(title).slice(0, 500).join(""));
    expect((payload as { capture: { title: string } }).capture.title).not.toMatch(/[\uD800-\uDBFF](?![\uDC00-\uDFFF])/);
  });
});

describe("submitShare", () => {
  const action = { id: "a1", type: "add_source", payload: { id: "s1", url: "u", intent: "queue" } };
  const fetchMock = jest.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    global.fetch = fetchMock as unknown as typeof fetch;
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  function respond(status: number, body: unknown = {}): void {
    fetchMock.mockResolvedValue({ status, ok: status >= 200 && status < 300, json: async () => body });
  }

  it.each(["applied", "duplicate"])("maps %s to saved and posts the action with the bearer key", async (result) => {
    respond(200, { results: [{ id: "a1", result, reason: null }] });

    await expect(submitShare(action, "key-1")).resolves.toBe("saved");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/sync\/push$/);
    expect(init.headers.Authorization).toBe("Bearer key-1");
    expect(JSON.parse(init.body)).toEqual({ actions: [action] });
  });

  it("maps a 401 to signed-out", async () => {
    respond(401);

    await expect(submitShare(action, "stale")).resolves.toBe("signed-out");
  });

  it("is signed-out without a key, and makes no request", async () => {
    await expect(submitShare(action, null)).resolves.toBe("signed-out");

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("maps a network failure and a 5xx to offline", async () => {
    fetchMock.mockRejectedValue(new TypeError("Network request failed"));
    await expect(submitShare(action, "key-1")).resolves.toBe("offline");

    respond(503);
    await expect(submitShare(action, "key-1")).resolves.toBe("offline");
  });

  it("throws the server's reason when the action is rejected", async () => {
    respond(200, { results: [{ id: "a1", result: "rejected", reason: "url is not http(s)" }] });

    await expect(submitShare(action, "key-1")).rejects.toThrow("url is not http(s)");
  });

  it("treats a request that never answers as offline", async () => {
    jest.useFakeTimers();
    fetchMock.mockReturnValue(new Promise(() => undefined));

    const outcome = submitShare(action, "key-1");
    await jest.advanceTimersByTimeAsync(15_000);

    await expect(outcome).resolves.toBe("offline");
  });
});

describe("shareDeepLink", () => {
  function parse(link: string): Record<string, string> {
    const query = link.slice("share?".length);
    return Object.fromEntries(query.split("&").map((pair) => pair.split("=", 2) as [string, string]));
  }

  it("carries url, intent, reaction and note, with the free-text values encoded so they survive the hop", () => {
    const link = shareDeepLink({ url: "https://a.com/x?q=1&r=2", choice: { ...finished, note: "100% a & b ~ c" } });
    const params = parse(link);

    expect(link.startsWith("share?")).toBe(true);
    expect(link).not.toMatch(/%/);
    expect(params).toMatchObject({ intent: "finished", reaction: "easy" });
    expect(decodeShareParam(params.url)).toBe("https://a.com/x?q=1&r=2");
    expect(decodeShareParam(params.note)).toBe("100% a & b ~ c");
    expect(Object.keys(params).sort()).toEqual(["intent", "note", "reaction", "url"]);
  });

  it("sends prep_me=1 for a queued, prepped share and no reaction", () => {
    const params = parse(shareDeepLink({ url: "https://a.com", choice: queued }));

    expect(params.prep_me).toBe("1");
    expect(params).not.toHaveProperty("reaction");
  });
});

describe("encodeShareParam", () => {
  it.each(["plain", "https://x.com/a?b=c&d=%20e#f", "~tilde~ and 100%", "emoji \u{1F600} é"])("round-trips %s", (value) => {
    expect(decodeShareParam(encodeShareParam(value))).toBe(value);
  });
});
