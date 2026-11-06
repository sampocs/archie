import { EMPTY_CHOICE } from "@/capture/types";

import { sharedCollectionItemFromParams, sharedSourceFromParams, type ShareParams } from "./deepLink";
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
      queuePrimer: false,
    });
  });

  it("keeps queue_primer for a queued share and drops reaction and note", () => {
    const params = routeParams(
      shareDeepLink({ url: "https://a.com/?x=1&y=2", choice: { ...EMPTY_CHOICE, intent: "queue", queuePrimer: true } }),
    );

    expect(sharedSourceFromParams({ ...params, reaction: "easy", note: "ignored" })).toEqual({
      url: "https://a.com/?x=1&y=2",
      intent: "queue",
      reaction: null,
      note: null,
      queuePrimer: true,
    });
  });

  it("returns null without a url or with an unknown intent", () => {
    expect(sharedSourceFromParams({ intent: "queue" })).toBeNull();
    expect(sharedSourceFromParams({ url: "https://a.com", intent: "later" })).toBeNull();
  });
});

describe("sharedCollectionItemFromParams", () => {
  const collectionChoice = { ...EMPTY_CHOICE, intent: "collection" as const };

  it("restores an existing pick", () => {
    const link = shareDeepLink({
      url: "https://a.com/?x=1&y=2",
      choice: { ...collectionChoice, collection: { kind: "existing", id: "col-1" } },
    });

    expect(sharedCollectionItemFromParams(routeParams(link))).toEqual({
      url: "https://a.com/?x=1&y=2",
      pick: { kind: "existing", id: "col-1" },
    });
  });

  it("restores a new pick's name exactly", () => {
    const link = shareDeepLink({
      url: "https://a.com",
      choice: { ...collectionChoice, collection: { kind: "new", name: "100% a & b ~ c" } },
    });

    expect(sharedCollectionItemFromParams(routeParams(link))).toEqual({
      url: "https://a.com",
      pick: { kind: "new", name: "100% a & b ~ c" },
    });
  });

  it("is null for other intents, a missing url, neither or both picks, and a blank name", () => {
    const url = "https%3A%2F%2Fa.com";

    expect(sharedCollectionItemFromParams({ url, intent: "queue", collection: "c" })).toBeNull();
    expect(sharedCollectionItemFromParams({ intent: "collection", collection: "c" })).toBeNull();
    expect(sharedCollectionItemFromParams({ url, intent: "collection" })).toBeNull();
    expect(sharedCollectionItemFromParams({ url, intent: "collection", collection: "c", collection_name: "N" })).toBeNull();
    expect(sharedCollectionItemFromParams({ url, intent: "collection", collection_name: "~20" })).toBeNull();
  });

  it("leaves sharedSourceFromParams null for a collection share", () => {
    expect(sharedSourceFromParams({ url: "https://a.com", intent: "collection", collection: "c" })).toBeNull();
  });
});
