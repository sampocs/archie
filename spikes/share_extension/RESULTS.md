# Spike: iOS share extension (2026-10-29)

A bare Expo SDK 54 app with an `expo-share-extension` share sheet. It shows exactly what each app hands over, checks that the extension can reach the network, and saves each share into the main app's list through a deep link.

## Install

1. Unlock the iPhone, plug it in, and trust the Mac if asked.
2. Run `spikes/share_extension/install.sh`.
3. The first time, approve the developer under iPhone Settings → General → VPN & Device Management.

To rebuild after code changes, run this from `ios/`:

```
xcodebuild -workspace CarlShareSpike.xcworkspace -scheme CarlShareSpike -configuration Release \
  -destination "generic/platform=iOS" -derivedDataPath build -allowProvisioningUpdates \
  DEVELOPMENT_TEAM=3W3H65F89G CODE_SIGN_STYLE=Automatic build
```

Running `expo prebuild --clean` regenerates `ios/` and re-adds the App Group entitlement. I removed it by hand because Apple's side doesn't have the group enabled for the extension's App ID, and links and text don't need it. The real app will need the App Group turned on once in Xcode, under the extension target's Signing & Capabilities.

## Results (2026-10-30, iPhone 15 Pro, iOS 26)

| Source | What arrives | Probe fetch from the extension | Notes |
|---|---|---|---|
| Spotify | **text only**, holding the URL (`?si=…&utm_source=native-share-menu`) | 200, 516 ms, real episode title | The title has HTML entities (`&#x27;`). The backend uses ld+json anyway. |
| YouTube | **text only**, holding the URL (`youtube.com/watch?v=…&is=…`) | 200, 2.4 s, title is just "YouTube" | The page renders with JS, so HTML gives no metadata. The backend uses oEmbed or a transcript API. |
| X | proper `url` | **failed after 151 ms** ("Network request failed") | x.com refuses a plain fetch. That doesn't matter, because the backend goes through fxtwitter. |
| Safari article | proper `url` | 200, 259 ms, correct title | |
| Safari selected text | not in the screenshot | | Retest |
| Apple Podcasts | didn't work | | Not investigated, because it's not a source we use |
| Paywalled article (NYT, from Safari) | page text via `preprocessingResults` (no `url` prop; the URL comes from the script) | 403 without page capture | **Works with page capture:** 5,106 words of real article body, title included. Without it, NYT returns 403 even on a gift link. |

- **URL extraction is required:** Spotify and YouTube share text, not a URL. Pulling the first URL out of the text worked for both.
- **Fetching:** the extension can reach the network (3 of 4 fetches succeeded; X blocks plain fetches), so it can call our backend directly. The extension should just send the URL and let the backend resolve it.
- **Handoff:** "Save to app" opens the main app with the record intact.
- **Finding it in the share sheet is slow.** It sat at the bottom of the "More" list. iOS doesn't let an app pin itself, so the fix is a one-time setup step: More → Edit → add it to Favorites, which puts it at the front of the row. iOS also moves frequently used targets forward on its own.
- **Paywalls:** the extension receives only the URL, not the page. A backend fetch won't have the user's Safari login, so subscriber articles need the extension to capture the page itself, using a JavaScript preprocessing file that runs inside Safari's page. **Safari page capture, tested 2026-10-31:** expo-share-extension's `preprocessingFile` runs `preprocessing.js` inside the Safari page and hands back the URL, the title, and the `<article>` text (or the body's).
  - It captured the full NYT article (5,106 words) as the logged-in user sees it.
  - An X share retested afterwards was unchanged: proper `url`, and the same fetch failure as before, which is X blocking plain fetches and expected.
  - `innerText` can repeat text such as captions, so the backend should still clean the capture, e.g. with a readability pass.
  - It only helps shares from Safari, not from in-app browsers.
