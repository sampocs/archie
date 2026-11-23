import {
  getAskAvailable,
  loadAskAvailable,
  resetAskAvailableForTests,
  subscribeAskAvailable,
} from "./askAvailableStore";

beforeEach(resetAskAvailableForTests);

describe("askAvailableStore", () => {
  it("is null for no session and for a key that has not answered", () => {
    expect(getAskAvailable(null)).toBeNull();
    expect(getAskAvailable("key-a")).toBeNull();
  });

  it("stays unknown when /me fails, then a retry reaches an already mounted consumer", async () => {
    const seen: (boolean | null)[] = [];
    const unsubscribe = subscribeAskAvailable(() => seen.push(getAskAvailable("key-a")));

    await loadAskAvailable("key-a", () => Promise.reject(new Error("offline")));
    expect(getAskAvailable("key-a")).toBeNull();
    expect(seen).toEqual([]);

    await loadAskAvailable("key-a", () => Promise.resolve(true));
    expect(getAskAvailable("key-a")).toBe(true);
    expect(seen).toEqual([true]);

    unsubscribe();
  });

  it("stores false for a non-whitelisted account", async () => {
    await loadAskAvailable("key-a", () => Promise.resolve(false));
    expect(getAskAvailable("key-a")).toBe(false);
  });

  it("asks once per key: skips when answered and while a fetch is running", async () => {
    const fetchWhitelisted = jest.fn(() => Promise.resolve(true));

    await Promise.all([loadAskAvailable("key-a", fetchWhitelisted), loadAskAvailable("key-a", fetchWhitelisted)]);
    await loadAskAvailable("key-a", fetchWhitelisted);

    expect(fetchWhitelisted).toHaveBeenCalledTimes(1);
  });

  it("resets on a new session key", async () => {
    await loadAskAvailable("key-a", () => Promise.resolve(true));

    expect(getAskAvailable("key-b")).toBeNull();
    await loadAskAvailable("key-b", () => Promise.resolve(false));
    expect(getAskAvailable("key-b")).toBe(false);
    expect(getAskAvailable("key-a")).toBe(true);
  });
});
