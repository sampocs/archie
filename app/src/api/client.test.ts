import { apiFetch, ClientError, NetworkError, UnauthorizedError } from "./client";

function respondWith(status: number): void {
  global.fetch = jest.fn(async () => ({ status, ok: status < 400, json: async () => ({}) })) as unknown as typeof fetch;
}

describe("apiFetch error mapping", () => {
  it.each([
    [401, UnauthorizedError],
    [422, ClientError],
    [503, NetworkError],
  ])("maps HTTP %i to %p", async (status, errorClass) => {
    respondWith(status);

    await expect(apiFetch("/x", { sessionKey: null })).rejects.toBeInstanceOf(errorClass);
  });
});

describe("API_URL", () => {
  const loadClient = (dev: boolean, configured?: string) => {
    const original = (globalThis as { __DEV__?: boolean }).__DEV__;
    (globalThis as { __DEV__?: boolean }).__DEV__ = dev;
    try {
      let loaded: typeof import("./client") | undefined;
      jest.isolateModules(() => {
        jest.doMock("expo-constants", () => ({
          __esModule: true,
          default: { expoConfig: { extra: { apiUrl: configured } } },
        }));
        loaded = require("./client");
      });
      return loaded!;
    } finally {
      (globalThis as { __DEV__?: boolean }).__DEV__ = original;
    }
  };

  it("uses the configured URL", () => {
    expect(loadClient(false, "https://api.example.com").API_URL).toBe("https://api.example.com");
  });

  it("falls back to localhost in debug builds", () => {
    expect(loadClient(true).API_URL).toBe("http://localhost:8000");
  });

  it("fails at load in a release build with no URL", () => {
    expect(() => loadClient(false)).toThrow(/EXPO_PUBLIC_API_URL/);
  });
});
