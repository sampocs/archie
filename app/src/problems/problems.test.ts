import { agoLabel, bannerText, mergeProblems, parseProblems, UNREACHABLE_AFTER_MS, type Problem } from "./problems";

const NOW = new Date("2026-11-13T12:00:00Z");
const row = { kind: "job_failing", key: "analyze", title: "Summaries failing", detail: "3 failed", since: "2026-11-13T10:00:00Z" };
const serverProblem: Problem = row;

describe("parseProblems", () => {
  it("keeps well-formed rows and drops malformed ones", () => {
    const body = {
      problems: [
        row,
        null,
        { ...row, kind: 3 },
        { ...row, key: undefined },
        { ...row, title: null },
        { ...row, detail: 5 },
        { ...row, since: "not a date" },
        { ...row, since: 1 },
      ],
    };

    expect(parseProblems(body)).toEqual([row]);
  });

  it("reads a body without a list as no problems", () => {
    expect(parseProblems(null)).toEqual([]);
    expect(parseProblems({})).toEqual([]);
    expect(parseProblems({ problems: "x" })).toEqual([]);
  });
});

describe("agoLabel", () => {
  const ago = (ms: number) => agoLabel(new Date(NOW.getTime() - ms).toISOString(), NOW);

  it("words each span", () => {
    expect(ago(30_000)).toBe("just now");
    expect(ago(5 * 60_000)).toBe("5 min ago");
    expect(ago(60 * 60_000)).toBe("1 hour ago");
    expect(ago(3 * 3_600_000)).toBe("3 hours ago");
    expect(ago(24 * 3_600_000)).toBe("1 day ago");
    expect(ago(49 * 3_600_000)).toBe("2 days ago");
  });

  it("treats a time in the future as just now", () => {
    expect(agoLabel("2026-11-13T13:00:00Z", NOW)).toBe("just now");
  });
});

describe("bannerText", () => {
  it("is singular for one and plural otherwise", () => {
    expect(bannerText(1)).toBe("1 thing needs a look");
    expect(bannerText(2)).toBe("2 things need a look");
  });
});

describe("mergeProblems", () => {
  const stale = NOW.getTime() - 3 * 24 * 3_600_000;

  it("shows nothing offline, even with server problems and a stale contact", () => {
    expect(mergeProblems({ serverProblems: [serverProblem], lastServerContactAt: stale, online: false, now: NOW })).toEqual([]);
  });

  it("passes the server's problems through when contact is recent", () => {
    const recent = NOW.getTime() - UNREACHABLE_AFTER_MS;

    expect(mergeProblems({ serverProblems: [serverProblem], lastServerContactAt: recent, online: true, now: NOW })).toEqual([
      serverProblem,
    ]);
  });

  it("adds nothing when the phone has never reached the server", () => {
    expect(mergeProblems({ serverProblems: [], lastServerContactAt: null, online: true, now: NOW })).toEqual([]);
  });

  it("adds the unreachable problem after the server's when contact is over a day old", () => {
    const merged = mergeProblems({ serverProblems: [serverProblem], lastServerContactAt: stale, online: true, now: NOW });

    expect(merged).toHaveLength(2);
    expect(merged[0]).toEqual(serverProblem);
    expect(merged[1]).toMatchObject({
      title: "Can't reach Archie's server",
      detail: "Last synced 3 days ago",
      since: new Date(stale).toISOString(),
    });
  });

  it("flags unreachable just past 24 hours", () => {
    const justOver = NOW.getTime() - UNREACHABLE_AFTER_MS - 1;

    expect(mergeProblems({ serverProblems: [], lastServerContactAt: justOver, online: true, now: NOW })).toHaveLength(1);
  });
});
