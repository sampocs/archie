import { EMPTY_CHOICE } from "@/capture/types";

import { sharedSourceFromParams, type ShareParams } from "./deepLink";
import { shareDeepLink } from "./submit";

// What the route receives: the extension's native side splits on "&" and "=", and expo-router decodes each value once.
function routeParams(link: string): ShareParams {
  const query = link.slice("share?".length);
  return Object.fromEntries(
    query.split("&").map((pair) => {
      const [key, value] = pair.split("=", 2);
      return [key, decodeURIComponent(value)];
    }),
  );
}

describe("sharedSourceFromParams", () => {
  it("restores a url and note that contain ?, &, = and ~ exactly as the share sheet had them", () => {
    const url = "https://a.com/x~y?q=1&r=a=b#frag";
    const note = "100% a & b = c ~ d";
    const link = shareDeepLink({ url, choice: { ...EMPTY_CHOICE, intent: "finished", reaction: "easy", note } });

    expect(sharedSourceFromParams(routeParams(link))).toEqual({
      url,
      intent: "finished",
      reaction: "easy",
      note,
      prepMe: false,
    });
  });

  it("keeps prep_me for a queued share and drops reaction and note", () => {
    const params = routeParams(
      shareDeepLink({ url: "https://a.com/?x=1&y=2", choice: { ...EMPTY_CHOICE, intent: "queue", prepMe: true } }),
    );

    expect(sharedSourceFromParams({ ...params, reaction: "easy", note: "ignored" })).toEqual({
      url: "https://a.com/?x=1&y=2",
      intent: "queue",
      reaction: null,
      note: null,
      prepMe: true,
    });
  });

  it("returns null without a url or with an unknown intent", () => {
    expect(sharedSourceFromParams({ intent: "queue" })).toBeNull();
    expect(sharedSourceFromParams({ url: "https://a.com", intent: "later" })).toBeNull();
  });
});
