import {
  senderFrom,
  senderHeadline,
  senderLabel,
  senderPrompt,
  senderSubject,
  senderToast,
  type PendingSenderSource,
} from "./senders";

const source = (overrides: Partial<PendingSenderSource>): PendingSenderSource => ({
  sender: "Example Weekly",
  senderAddress: "hello@example.com",
  title: "Issue 12: Rates",
  ...overrides,
});

describe("pending sender words", () => {
  it("names the sender by display name, then address, then Unknown", () => {
    expect(senderLabel(source({ sender: "  Example Weekly " }))).toBe("Example Weekly");
    expect(senderLabel(source({ sender: "  " }))).toBe("hello@example.com");
    expect(senderLabel(source({ sender: null, senderAddress: "news@example.org" }))).toBe("news@example.org");
    expect(senderLabel(source({ sender: null, senderAddress: null }))).toBe("Unknown");
  });

  it("builds the headline, toasts and prompt from the label", () => {
    const nameless = source({ sender: null, senderAddress: "news@example.org" });

    expect(senderHeadline(source({}))).toBe("New sender: Example Weekly");
    expect(senderHeadline(nameless)).toBe("New sender: news@example.org");
    expect(senderToast(source({}), "allowed")).toBe("Example Weekly allowed");
    expect(senderToast(nameless, "blocked")).toBe("news@example.org blocked");
    expect(senderPrompt(source({}))).toBe("This email is from a new sender: Example Weekly.");
    expect(senderPrompt(nameless)).toBe("This email is from a new sender: news@example.org.");
  });

  it("reads the from line as address and time, or the time alone without an address", () => {
    expect(senderFrom(source({}), "2h ago")).toBe("hello@example.com · 2h ago");
    expect(senderFrom(source({ senderAddress: null }), "2h ago")).toBe("2h ago");
    expect(senderFrom(source({ senderAddress: "  " }), "2h ago")).toBe("2h ago");
  });

  it("gives the subject trimmed, or null so the line is omitted", () => {
    expect(senderSubject(source({ title: "  Issue 12  " }))).toBe("Issue 12");
    expect(senderSubject(source({ title: null }))).toBeNull();
    expect(senderSubject(source({ title: "   " }))).toBeNull();
  });
});
