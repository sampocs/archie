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

| Source | Result |
|---|---|
| Spotify | Works |
| X | Works |
| YouTube | Works |
| Safari article | Works |
| Safari selected text | Works |
| Apple Podcasts | Didn't work. Not investigated, because it's not a source we use. |
| Paywalled article | Not yet tested |

- **Fetching:** the extension can reach the network, so it can call our backend directly.
- **Handoff:** "Save to app" opens the main app with the record intact.
- **Finding it in the share sheet is slow.** It sat at the bottom of the "More" list. iOS doesn't let an app pin itself, so the fix is a one-time setup step: More → Edit → add it to Favorites, which puts it at the front of the row. iOS also moves frequently used targets forward on its own.
- **Paywalls:** the extension receives only the URL, not the page. A backend fetch won't have the user's Safari login, so subscriber articles need the extension to capture the page itself, using a JavaScript preprocessing file that runs inside Safari's page. That's the separate "Safari paywall capture" spike.
