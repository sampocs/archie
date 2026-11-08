import {
  briefDomain,
  briefReadingMinutes,
  briefSinceLabel,
  briefTitle,
  previewLines,
  storiesInOrder,
  todayBrief,
  type BriefContent,
  type BriefRow,
  type BriefStory,
} from "./brief";

// jest.config.js pins TZ to America/New_York.
const now = new Date(2026, 10, 4, 9);

function story(headline: string, overrides: Partial<BriefStory> = {}): BriefStory {
  return { headline, body: "", why: "", detail: "", importance: 5, source_ids: ["n1"], ...overrides };
}

function content(overrides: Partial<BriefContent> = {}): BriefContent {
  return { domains: [], also: [], essays: [], ...overrides };
}

function brief(overrides: Partial<BriefRow> = {}): BriefRow {
  return {
    id: "b1", status: "open", content: null, sourceIds: "[]", since: null, version: 1,
    createdAt: now.toISOString(), updatedAt: now.toISOString(), doneAt: null,
    ...overrides,
  };
}

type NewsletterFields = {
  state: string; createdAt: string; processing: string; kind: string; confirmUrl: string | null;
};
const newsletter = (overrides: Partial<NewsletterFields> = {}) => ({
  kind: "newsletter", state: "inbox", processing: "ready", createdAt: new Date(2026, 10, 3, 8).toISOString(), confirmUrl: null,
  ...overrides,
});

describe("storiesInOrder", () => {
  it("keeps the stored order of domains and stories and numbers stories across domains", () => {
    const ordered = storiesInOrder(
      content({
        domains: [
          { domain: "Politics", stories: [story("p1", { importance: 3 }), story("p2", { importance: 9 })] },
          { domain: "crypto", stories: [story("c1")] },
        ],
      }),
    );

    expect(ordered.map((entry) => [entry.index, entry.domain, entry.story.headline])).toEqual([
      [0, "Politics", "p1"],
      [1, "Politics", "p2"],
      [2, "Crypto", "c1"],
    ]);
  });

  it("files an unknown domain under Other", () => {
    expect(briefDomain("Business")).toBe("Other");
    expect(briefDomain(" software ENGINEERING ")).toBe("Software engineering");
  });
});

describe("briefReadingMinutes", () => {
  it("counts story bodies, their why and the also lines at 220 words a minute, rounded up", () => {
    const words = (count: number) => Array.from({ length: count }, () => "word").join(" ");
    const brief = content({
      domains: [{ domain: "AI", stories: [story("h", { body: words(200), why: words(20), detail: words(500) })] }],
      also: [{ text: words(1), source_ids: [] }],
      essays: [{ source_id: "e1", pitch: words(500) }],
    });

    expect(briefReadingMinutes(brief)).toBe(2);
  });

  it("is at least a minute", () => {
    expect(briefReadingMinutes(content())).toBe(1);
  });
});

describe("briefSinceLabel", () => {
  it("says today, yesterday, else the weekday, by calendar day", () => {
    expect(briefSinceLabel(new Date(2026, 10, 4, 0, 5).toISOString(), now)).toBe("since today");
    expect(briefSinceLabel(new Date(2026, 10, 3, 23, 50).toISOString(), now)).toBe("since yesterday");
    expect(briefSinceLabel(new Date(2026, 10, 2, 8).toISOString(), now)).toBe("since Mon");
  });
});

test("briefTitle names the phone's today", () => {
  expect(briefTitle(now)).toBe("Wednesday's brief");
});

describe("previewLines", () => {
  const stories = (count: number) =>
    content({ domains: [{ domain: "AI", stories: Array.from({ length: count }, (_, index) => story(`h${index}`)) }] });
  const essays = (count: number) =>
    Array.from({ length: count }, (_, index) => ({ source_id: `e${index}`, pitch: "" }));

  it("shows the first three headlines and how many stories and essays are left", () => {
    expect(previewLines({ ...stories(6), essays: essays(2) })).toEqual({
      headlines: ["h0", "h1", "h2"],
      more: "+ 3 more, and 2 essays",
    });
    expect(previewLines(stories(4))).toEqual({ headlines: ["h0", "h1", "h2"], more: "+ 1 more" });
    expect(previewLines({ ...stories(2), essays: essays(1) })).toEqual({ headlines: ["h0", "h1"], more: "+ 1 essay" });
    expect(previewLines(stories(3))).toEqual({ headlines: ["h0", "h1", "h2"], more: null });
  });
});

describe("todayBrief", () => {
  const ready = JSON.stringify(content({ domains: [{ domain: "AI", stories: [story("h")] }] }));

  it("previews the open brief once it has content, whatever is waiting", () => {
    const briefs = [brief({ id: "old", status: "done", content: ready }), brief({ content: ready })];
    const result = todayBrief(briefs, []);

    expect(result).toMatchObject({ kind: "ready", brief: { id: "b1" } });
  });

  it("says the brief is being written while inbox newsletters, however old, wait for its first content", () => {
    const sources = [
      newsletter(),
      newsletter({ processing: "processing" }),
      newsletter({ state: "briefed" }),
      newsletter({ state: "queued" }),
      newsletter({ processing: "failed" }),
      newsletter({ createdAt: new Date(2026, 10, 1, 8).toISOString() }),
      newsletter({ kind: "article" }),
    ];

    expect(todayBrief([brief()], sources)).toEqual({ kind: "writing", newsletters: 3 });
    expect(todayBrief([], sources)).toEqual({ kind: "writing", newsletters: 3 });
  });

  it("never counts a signup confirmation, so one alone makes no brief and a real newsletter still counts once", () => {
    const confirmation = newsletter({ confirmUrl: "https://example.com/confirm-signup" });

    expect(todayBrief([], [confirmation])).toBeNull();
    expect(todayBrief([], [confirmation, newsletter()])).toEqual({ kind: "writing", newsletters: 1 });
  });

  it("shows nothing when nothing is unbriefed, even with a done brief", () => {
    expect(todayBrief([brief({ status: "done", content: ready })], [newsletter({ state: "briefed" })])).toBeNull();
  });
});
